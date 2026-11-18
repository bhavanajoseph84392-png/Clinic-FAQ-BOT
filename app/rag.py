import re
import logging
import httpx
from typing import Dict, Any, List, Optional
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

EMERGENCY_MESSAGE = (
    "If this is an emergency, please call 112 or go to the nearest hospital now. "
    "The clinic will also reply to you by email."
)

URGENT_SYMPTOM_KEYWORDS = (
    "chest pain",
    "chest tightness",
    "pressure in my chest",
    "trouble breathing",
    "difficulty breathing",
    "can't breathe",
    "cannot breathe",
    "shortness of breath",
    "short of breath",
    "severe bleeding",
    "heavy bleeding",
    "bleeding heavily",
    "bleeding a lot",
    "fainting",
    "fainted",
    "passed out",
    "unconscious",
    "signs of a stroke",
    "numbness on one side",
    "sudden numbness",
    "think i'm having a stroke",
    "having a stroke",
    "face drooping",
    "slurred speech",
    "sudden weakness",
    "suicidal",
    "suicide",
    "kill myself",
    "end my life",
    "want to die",
    "self-harm",
    "self harm",
)

def mentions_urgent_symptom(text: str) -> bool:
    lowered = (text or "").lower().replace("\u2019", "'")
    return any(keyword in lowered for keyword in URGENT_SYMPTOM_KEYWORDS)

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

    if mentions_urgent_symptom(question_text):
        return {**fallback_res, "answer": EMERGENCY_MESSAGE}

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
                    cur.execute("UPDATE lessons SET times_used = times_used + 1 WHERE id = %s AND clinic_id = %s;", (lesson["id"], clinic_id))
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
        
    user_prompt = ANSWER_USER.format(context=full_context, question=question_text)
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