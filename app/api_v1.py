import secrets
import logging
from typing import List, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from app.auth import hash_token
from app.db import get_db, tenant_tx
from app.tenancy import resolve_api_key_clinic
from app.rag import answer_question, FALLBACK_MESSAGE

logger = logging.getLogger("clinic_faq.api")
router = APIRouter(prefix="/api/v1", tags=["Clinic FAQ Public API"])

# Pydantic Schemas for typed OpenAPI documentation
class AskRequest(BaseModel):
    question: str = Field(..., description="The patient or FAQ question to answer", json_schema_extra={"example": "What are your consultation hours?"})

class AskResponse(BaseModel):
    answer: str = Field(..., description="Grounded answer or official clinic fallback")
    status: str = Field(..., description="answered or pending")
    source: Optional[str] = Field(None, description="Title of cited clinic knowledge item or lesson")
    question_id: str = Field(..., description="Unique question tracking ID")

class QuestionItem(BaseModel):
    id: str
    patient_name: Optional[str]
    patient_email: Optional[str]
    source: str
    text: str
    status: str
    asked_at: str

class QuestionsListResponse(BaseModel):
    items: List[QuestionItem]
    next_cursor: Optional[str] = None

def _enforce_rate_limit(api_key_id: str, limit_per_min: int):
    """
    Checks and increments rate limit counter per current minute window.
    Raises 429 with Retry-After header if exceeded.
    """
    now = datetime.now(timezone.utc)
    window_start = now.replace(second=0, microsecond=0)
    
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO rate_limit_counters (api_key_id, window_start, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (api_key_id, window_start)
                DO UPDATE SET count = rate_limit_counters.count + 1
                RETURNING count;
            """, (api_key_id, window_start))
            current_count = cur.fetchone()[0]
            
            if current_count > limit_per_min:
                seconds_remaining = 60 - now.second
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="API rate limit exceeded. Please retry later.",
                    headers={"Retry-After": str(seconds_remaining)}
                )

def _authenticate_key(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header with Bearer token"
        )
    raw_key = authorization.split("Bearer ", 1)[1].strip()
    key_info = resolve_api_key_clinic(raw_key)
    _enforce_rate_limit(key_info["id"], key_info["rate_limit_per_min"])
    return key_info

@router.post("/ask", response_model=AskResponse, summary="Submit a question to the clinic chatbot")
async def ask_endpoint(payload: AskRequest, request: Request, authorization: Optional[str] = Header(None)):
    """
    Submits a question to the clinic's isolated AI FAQ chatbot.
    Returns grounded clinic answers or escalates to Pending question.
    """
    key_info = _authenticate_key(authorization)
    clinic_id = key_info["clinic_id"]
    question_text = payload.question.strip()

    if not question_text:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = answer_question(clinic_id, question_text)
    is_fallback = (result["answer"] == FALLBACK_MESSAGE)
    q_status = "pending" if is_fallback else "answered"

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO questions (clinic_id, source, text, status)
                VALUES (%s, 'api', %s, %s)
                RETURNING id;
            """, (clinic_id, question_text, q_status))
            qid = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO answers (clinic_id, question_id, text, kind, source_chunk_ids, source_title, lesson_id, confidence, tokens_in, tokens_out)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                clinic_id, qid, result["answer"], result["kind"],
                result["source_chunk_ids"], result["source_title"],
                result["lesson_id"], result["confidence"],
                result["tokens_in"], result["tokens_out"]
            ))

    return AskResponse(
        answer=result["answer"],
        status=q_status,
        source=result["source_title"],
        question_id=str(qid)
    )

@router.get("/questions", response_model=QuestionsListResponse, summary="Retrieve clinic questions by status")
async def get_questions(
    request: Request,
    authorization: Optional[str] = Header(None),
    status: str = Query("pending", description="Filter by status: pending, answered, resolved"),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None, description="Pagination cursor")
):
    """
    Retrieves questions strictly scoped to the authenticated clinic.
    """
    key_info = _authenticate_key(authorization)
    clinic_id = key_info["clinic_id"]

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            query = """
                SELECT id, patient_name, patient_email, source, text, status, asked_at
                FROM questions
                WHERE status = %s
            """
            params = [status]
            if cursor:
                query += " AND asked_at < %s"
                params.append(cursor)

            query += " ORDER BY asked_at DESC LIMIT %s;"
            params.append(limit + 1)

            cur.execute(query, params)
            rows = cur.fetchall()

    items = []
    has_more = len(rows) > limit
    output_rows = rows[:limit]

    for r in output_rows:
        items.append(QuestionItem(
            id=str(r[0]),
            patient_name=r[1],
            patient_email=r[2],
            source=r[3],
            text=r[4],
            status=r[5],
            asked_at=r[6].isoformat() if r[6] else ""
        ))

    next_cursor = output_rows[-1][6].isoformat() if has_more and output_rows and output_rows[-1][6] else None

    return QuestionsListResponse(
        items=items,
        next_cursor=next_cursor
    )

# Key Generation Helper Functions for Admin UI
def generate_clinic_api_key(clinic_id: str, name: str) -> tuple[str, str]:
    """Generates a raw key `cfb_<32chars>`, stores sha256 hash, returns (raw_key, key_prefix)."""
    random_part = secrets.token_urlsafe(24)
    raw_key = f"cfb_{random_part}"
    prefix = raw_key[:8]
    key_hash = hash_token(raw_key)

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO api_keys (clinic_id, name, key_prefix, key_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
            """, (clinic_id, name, prefix, key_hash))
            key_id = cur.fetchone()[0]

    return raw_key, prefix
