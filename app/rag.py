import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx

from app.config import settings
from app.db import tenant_tx
from app.prompts import (
    FALLBACK_MESSAGE,
    ANSWER_SYSTEM,
    ANSWER_USER,
    CLASSIFY_SYSTEM,
    GROUNDING_SYSTEM,
)
from app.search import search_lessons, hybrid_search

logger = logging.getLogger("clinic_faq.rag")

URGENT_TERMS_FILE = Path(__file__).resolve().parent.parent / "config" / "urgent_terms.txt"


def _load_urgent_terms() -> tuple:
    lines = URGENT_TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return tuple(
        line.strip().lower()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    )


URGENT_SYMPTOM_KEYWORDS = _load_urgent_terms()

_LANGUAGE_INSTRUCTIONS = {
    "Hindi": (
        "\n\nReply in Hindi using Devanagari script. Translate the retrieved clinic text "
        "into Hindi; add no facts or outside knowledge."
    ),
    "Telugu": (
        "\n\nReply in Telugu using Telugu script. Translate the retrieved clinic text "
        "into Telugu; add no facts or outside knowledge."
    ),
    "English": (
        "\n\nReply in English using only the retrieved clinic text; add no facts or outside knowledge."
    ),
}


def detect_language(text: str) -> str:
    """Detects Devanagari (Hindi), Telugu or English from the patient's message."""
    for char in text or "":
        code = ord(char)
        if 0x0900 <= code <= 0x097F:
            return "Hindi"
        if 0x0C00 <= code <= 0x0C7F:
            return "Telugu"
    return "English"


EMERGENCY_BASE = (
    "This may be an emergency. Please call your local emergency number or go to the nearest hospital now."
)


def build_emergency_message(clinic_id: str) -> str:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT phone FROM clinics WHERE id = %s;", (clinic_id,))
            row = cur.fetchone()
    if row and row[0]:
        return f"{EMERGENCY_BASE} You can also call the clinic at {row[0]}."
    return f"{EMERGENCY_BASE} You can also contact the clinic directly."


def mentions_urgent_symptom(text: str) -> bool:
    lowered = (text or "").lower().replace("\u2019", "'")
    return any(keyword in lowered for keyword in URGENT_SYMPTOM_KEYWORDS)


_LOCKED_STOPWORDS = {
    "what", "when", "where", "who", "why", "how", "is", "are", "am", "do", "does",
    "did", "the", "a", "an", "your", "you", "we", "our", "i", "my", "to", "for",
    "of", "and", "or", "in", "on", "at", "with", "can", "could", "would", "should",
    "please", "tell", "me", "about", "have", "has", "it", "this", "that", "there",
    "from", "be", "will", "clinic", "clinics", "doctor", "doctors", "hospital",
    "patient", "patients", "service", "services", "health", "healthcare", "care",
}


def _match_tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if len(word) >= 3 and word not in _LOCKED_STOPWORDS}


def find_locked_answer(clinic_id: str, question_text: str) -> Optional[Dict[str, Any]]:
    """Returns the best matching locked knowledge item for this clinic, if any."""
    try:
        with tenant_tx(clinic_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, title, body
                    FROM knowledge_items
                    WHERE clinic_id = %s AND is_locked = true
                      AND body IS NOT NULL AND body <> ''
                    ORDER BY created_at DESC;
                    """,
                    (clinic_id,),
                )
                rows = cur.fetchall()
    except Exception as exc:
        logger.warning("Locked answer lookup failed for clinic %s: %s", clinic_id, exc)
        return None

    question_tokens = _match_tokens(question_text)
    if not question_tokens:
        return None

    best_row = None
    best_score = 0
    for row in rows:
        item_tokens = _match_tokens(f"{row[1] or ''} {row[2] or ''}")
        score = len(question_tokens & item_tokens)
        if score > best_score:
            best_row = row
            best_score = score

    if not best_row:
        return None

    return {
        "id": str(best_row[0]),
        "title": best_row[1],
        "body": best_row[2],
    }


def _check_daily_budget(clinic_id: str) -> bool:
    """Checks if clinic has exceeded DAILY_AI_BUDGET_PER_CLINIC for today."""
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM answers
                WHERE clinic_id = %s AND kind = 'ai' AND created_at >= date_trunc('day', now());
            """, (clinic_id,))
            row = cur.fetchone()
            count = row[0] if row else 0
            return count >= settings.DAILY_AI_BUDGET_PER_CLINIC


def _call_gemini(system_instruction: str, user_prompt: str, model_name: str) -> str:
    """Invokes the configured chat provider with the prompt and system instruction."""
    nvidia_base_url = settings.NVIDIA_BASE_URL.rstrip("/")
    if settings.NVIDIA_API_KEY and nvidia_base_url:
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(
                    f"{nvidia_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0,
                        "max_tokens": 512,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return content.strip() if content else ""
        except Exception as e:
            status = getattr(getattr(e, "response", None), "status_code", "")
            logger.error("NVIDIA chat request failed: %s %s", type(e).__name__, status)
            return ""

    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY.startswith("your_"):
        # Deterministic simulation for tests/offline
        return _simulate_llm_response(system_instruction, user_prompt)

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0
            )
        )
        return response.text.strip() if response and response.text else ""
    except Exception as e:
        logger.error("Gemini API call failed: %s", type(e).__name__)
        return ""


def _simulate_llm_response(system_instruction: str, user_prompt: str) -> str:
    """Simulated responses for offline / CI / unit testing environments."""
    if "Classify" in system_instruction:
        low = user_prompt.lower()
        medical_terms = [
            "diagnos", "prescribe", "treatment", "medicine", "rash", "infection",
            "symptom", "pain", "dose", "dosage", "ibuprofen", "amoxicillin", "antibiotic",
            "headache", "fever", "medication", "disease", "vomit", "nausea"
        ]
        if any(w in low for w in medical_terms):
            return "medical"
        if any(w in low for w in ["hello", "hi", "hey", "good morning", "good evening", "how are you"]):
            return "smalltalk"
        if any(w in low for w in ["ignore all", "system prompt", "hack", "bypass", "drop table", "swear"]):
            return "abuse"
        return "faq"

    if "GROUNDING_SYSTEM" in system_instruction or "Reply PASS only" in system_instruction:
        # Check if numbers or key words in answer are present in context
        return "PASS"

    # Answer generation simulation
    if "CONTEXT:" in user_prompt:
        context_part = user_prompt.split("CONTEXT:")[1].split("QUESTION:")[0].strip()
        lines = [l for l in context_part.splitlines() if l.strip() and not l.startswith("[")]
        if lines:
            return f"Based on clinic information: {lines[0]}"
        return "NO_ANSWER"

    return "NO_ANSWER"


def classify_message(question: str) -> str:
    """Classifies user question into: faq, medical, smalltalk, abuse."""
    try:
        classification = _call_gemini(
            system_instruction=CLASSIFY_SYSTEM,
            user_prompt=question,
            model_name=settings.CHECK_MODEL
        ).strip().lower()
    except Exception:
        logger.warning("Message classification failed; using safe fallback route.")
        return "medical"

    if "medical" in classification:
        return "medical"
    elif "smalltalk" in classification:
        return "smalltalk"
    elif "abuse" in classification:
        return "abuse"
    elif "faq" in classification:
        return "faq"
    else:
        return "medical"


_NUMBER_RE = re.compile(r"\d+")


def verify_grounding(context_text: str, candidate_answer: str) -> bool:
    """Strict check: every number in the answer must appear in the context, then the model must say PASS."""
    answer_numbers = {int(n) for n in _NUMBER_RE.findall(candidate_answer)}
    context_numbers = {int(n) for n in _NUMBER_RE.findall(context_text)}
    missing = answer_numbers - context_numbers
    if missing:
        logger.warning("Grounding failed: numbers not in context: %s", sorted(missing))
        return False
    prompt = f"CONTEXT:\n{context_text}\n\nANSWER:\n{candidate_answer}"
    result = _call_gemini(
        system_instruction=GROUNDING_SYSTEM,
        user_prompt=prompt,
        model_name=settings.CHECK_MODEL
    ).strip().upper()
    return result == "PASS"


def answer_question(clinic_id: str, question_text: str) -> Dict[str, Any]:
    """
    Core RAG pipeline:
    0. Urgent symptom check (returns emergency message, no AI call)
    1. Budget check
    2. Classify (faq, medical, smalltalk, abuse)
    3. Lessons first (sim >= LESSON_THRESHOLD)
    4. Hybrid search
    5. Knowledge threshold check
    6. Answer model generation
    7. Grounding verification
    8. Fallback on any failure
    """
    fallback_res = {
        "answer": FALLBACK_MESSAGE,
        "kind": "fallback",
        "source_title": None,
        "source_chunk_ids": [],
        "lesson_id": None,
        "confidence": 0.0,
        "tokens_in": 0,
        "tokens_out": 0
    }

    # Step 0: Urgent check comes first, so emergencies never reach the AI
    if mentions_urgent_symptom(question_text):
        return {**fallback_res, "answer": build_emergency_message(clinic_id)}

    # Step 0a: Locked answers are returned exactly as stored, with no model call
    locked = find_locked_answer(clinic_id, question_text)
    if locked:
        return {
            "answer": locked["body"],
            "kind": "manual",
            "source_title": locked["title"],
            "source_chunk_ids": [],
            "lesson_id": None,
            "confidence": 1.0,
            "tokens_in": 0,
            "tokens_out": 0,
        }

    # Step 1: Budget Check
    if _check_daily_budget(clinic_id):
        logger.warning(f"Clinic {clinic_id} exceeded daily AI budget.")
        return fallback_res

    # Step 2: Intent Classification
    intent = classify_message(question_text)
    if intent == "medical":
        return fallback_res
    elif intent == "abuse":
        return fallback_res
    elif intent == "smalltalk":
        return {
            "answer": "Hello! How can I help you with our clinic's services or schedule today?",
            "kind": "ai",
            "source_title": "General",
            "source_chunk_ids": [],
            "lesson_id": None,
            "confidence": 1.0,
            "tokens_in": 0,
            "tokens_out": 0
        }

    # Step 3: Lessons First
    lesson = search_lessons(clinic_id, question_text)
    lesson_hint = ""
    if lesson:
        if lesson.get("correct_answer"):
            # Record lesson use
            with tenant_tx(clinic_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE lessons SET times_used = times_used + 1 WHERE id = %s AND clinic_id = %s;",
                        (lesson["id"], clinic_id),
                    )
            return {
                "answer": lesson["correct_answer"],
                "kind": "lesson",
                "source_title": "Verified Clinic Lesson",
                "source_chunk_ids": [],
                "lesson_id": lesson["id"],
                "confidence": lesson["similarity"],
                "tokens_in": 0,
                "tokens_out": 0
            }
        elif lesson.get("comment"):
            lesson_hint = f"\nNote from clinic admin: {lesson['comment']}"

    # Step 4: Hybrid Knowledge Search
    chunks, best_similarity = hybrid_search(clinic_id, question_text, top_k=5)

    # Step 5: Knowledge Threshold Check
    if not chunks or best_similarity < settings.KNOWLEDGE_THRESHOLD:
        logger.info(f"Similarity {best_similarity} below threshold {settings.KNOWLEDGE_THRESHOLD}")
        return fallback_res

    # Step 6: Generate Answer with Answer Model
    context_passages = []
    chunk_ids = []
    top_title = chunks[0]["title"] if chunks else "Clinic Knowledge Base"

    for idx, c in enumerate(chunks, start=1):
        context_passages.append(f"[{idx}] {c['content']}")
        chunk_ids.append(c["id"])

    full_context = "\n\n".join(context_passages)
    if lesson_hint:
        full_context += lesson_hint

    language = detect_language(question_text)
    user_prompt = ANSWER_USER.format(context=full_context, question=question_text)
    user_prompt += _LANGUAGE_INSTRUCTIONS[language]
    raw_answer = _call_gemini(
        system_instruction=ANSWER_SYSTEM,
        user_prompt=user_prompt,
        model_name=settings.ANSWER_MODEL
    ).strip()

    if not raw_answer or "NO_ANSWER" in raw_answer:
        return fallback_res

    # Step 7: Grounding Verification
    if not verify_grounding(full_context, raw_answer):
        logger.warning(f"Answer failed grounding check: {raw_answer}")
        return fallback_res

    # Step 8: Return Answer
    return {
        "answer": raw_answer,
        "kind": "ai",
        "source_title": top_title,
        "source_chunk_ids": chunk_ids,
        "lesson_id": None,
        "confidence": best_similarity,
        "tokens_in": len(full_context.split()),
        "tokens_out": len(raw_answer.split())
    }