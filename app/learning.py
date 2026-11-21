import logging
from typing import Dict, Any, List, Optional
from app.db import tenant_tx
from app.jobs import enqueue_job
from app.rag import answer_question

logger = logging.getLogger("clinic_faq.learning")

def rate_answer(clinic_id: str, answer_id: str, value: str, correct_answer: Optional[str] = None, comment: Optional[str] = None) -> Dict[str, Any]:
    value = value.lower()
    if value not in ("good", "bad"):
        raise ValueError("Rating value must be 'good' or 'bad'")

    if value == "bad" and not (correct_answer and correct_answer.strip()) and not (comment and comment.strip()):
        raise ValueError("A bad rating requires either a correct answer or an explanatory comment.")

    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            # Check answer exists and belongs to clinic
            cur.execute("""
                SELECT a.id, a.text, q.text, q.id
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                WHERE a.id = %s AND a.clinic_id = %s;
            """, (answer_id, clinic_id))
            ans_row = cur.fetchone()
            if not ans_row:
                raise ValueError("Answer not found")

            aid, bad_ans_text, q_text, q_id = ans_row

            # Upsert rating
            cur.execute("""
                INSERT INTO ratings (clinic_id, answer_id, value, correct_answer, comment)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (answer_id) WHERE session_id IS NULL DO UPDATE
                SET value = EXCLUDED.value, correct_answer = EXCLUDED.correct_answer, comment = EXCLUDED.comment, rated_at = now()
                RETURNING id;
            """, (clinic_id, answer_id, value, correct_answer, comment))
            rating_id = cur.fetchone()[0]

            lesson_id = None
            if value == "bad":
                # Create a lesson
                cur.execute("""
                    INSERT INTO lessons (clinic_id, rating_id, question_text, bad_answer, correct_answer, comment, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, true)
                    RETURNING id;
                """, (clinic_id, rating_id, q_text, bad_ans_text, correct_answer, comment))
                lesson_id = cur.fetchone()[0]

                # Enqueue embedding generation for the lesson
                enqueue_job(clinic_id, "embed_lesson", {"lesson_id": str(lesson_id), "question_text": q_text})

            return {
                "success": True,
                "rating_id": str(rating_id),
                "lesson_id": str(lesson_id) if lesson_id else None
            }

def list_lessons(clinic_id: str) -> List[Dict[str, Any]]:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, question_text, bad_answer, correct_answer, comment, enabled, times_used, created_at
                FROM lessons
                WHERE clinic_id = %s
                ORDER BY created_at DESC;
            """, (clinic_id,))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "question_text": r[1],
                    "bad_answer": r[2],
                    "correct_answer": r[3],
                    "comment": r[4],
                    "enabled": r[5],
                    "times_used": r[6],
                    "created_at": r[7].strftime("%Y-%m-%d %H:%M:%S") if r[7] else ""
                }
                for r in rows
            ]

def toggle_lesson(clinic_id: str, lesson_id: str, enabled: bool) -> bool:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE lessons SET enabled = %s WHERE id = %s AND clinic_id = %s RETURNING id;", (enabled, lesson_id, clinic_id))
            return cur.fetchone() is not None

def delete_lesson(clinic_id: str, lesson_id: str) -> bool:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM lessons WHERE id = %s AND clinic_id = %s RETURNING id;", (lesson_id, clinic_id))
            return cur.fetchone() is not None

def ask_again(clinic_id: str, old_answer_id: str) -> Dict[str, Any]:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT a.id, a.text, a.kind, a.source_title, a.lesson_id, q.id, q.text
                FROM answers a
                JOIN questions q ON a.question_id = q.id
                WHERE a.id = %s AND a.clinic_id = %s;
            """, (old_answer_id, clinic_id))
            row = cur.fetchone()
            if not row:
                raise ValueError("Original answer not found")

            aid, old_text, old_kind, old_source, old_lesson, qid, q_text = row

    # Rerun answer pipeline
    new_result = answer_question(clinic_id, q_text)

    # Insert new answers row referencing replaces_answer_id
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO answers (clinic_id, question_id, text, kind, source_chunk_ids, source_title, lesson_id, confidence, replaces_answer_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                clinic_id, qid, new_result["answer"], new_result["kind"],
                new_result["source_chunk_ids"], new_result["source_title"],
                new_result["lesson_id"], new_result["confidence"], old_answer_id
            ))
            new_ans_id = cur.fetchone()[0]

            if new_result["kind"] == "lesson" and new_result["lesson_id"]:
                cur.execute("""
                    INSERT INTO lesson_uses (clinic_id, lesson_id, answer_id)
                    VALUES (%s, %s, %s);
                """, (clinic_id, new_result["lesson_id"], new_ans_id))

    return {
        "question": q_text,
        "old_answer": {
            "id": str(aid),
            "text": old_text,
            "kind": old_kind,
            "source_title": old_source,
            "lesson_id": str(old_lesson) if old_lesson else None
        },
        "new_answer": {
            "id": str(new_ans_id),
            "text": new_result["answer"],
            "kind": new_result["kind"],
            "source_title": new_result["source_title"],
            "lesson_id": str(new_result["lesson_id"]) if new_result["lesson_id"] else None,
            "lesson_used": new_result["kind"] == "lesson" or new_result["lesson_id"] is not None
        }
    }


def format_top_unanswered(rows):
    return [{"question": r[0], "count": r[1]} for r in rows]


def get_analytics(clinic_id: str) -> Dict[str, Any]:
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            # Weekly good and bad
            cur.execute("""
                SELECT to_char(date_trunc('week', rated_at), 'YYYY-"W"IW') AS wk,
                       value,
                       COUNT(*)
                FROM ratings
                WHERE clinic_id = %s
                GROUP BY wk, value
                ORDER BY wk ASC;
            """, (clinic_id,))
            rating_rows = cur.fetchall()

            # Weekly lessons used
            cur.execute("""
                SELECT to_char(date_trunc('week', used_at), 'YYYY-"W"IW') AS wk,
                       COUNT(*)
                FROM lesson_uses
                WHERE clinic_id = %s
                GROUP BY wk
                ORDER BY wk ASC;
            """, (clinic_id,))
            lesson_rows = cur.fetchall()

            # Overall summary counts
            cur.execute("SELECT COUNT(*) FROM questions WHERE clinic_id = %s;", (clinic_id,))
            total_questions = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM questions WHERE status = 'pending' AND clinic_id = %s;", (clinic_id,))
            total_pending = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM ratings WHERE value = 'good' AND clinic_id = %s;", (clinic_id,))
            total_good = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM ratings WHERE value = 'bad' AND clinic_id = %s;", (clinic_id,))
            total_bad = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM lessons WHERE clinic_id = %s;", (clinic_id,))
            total_lessons = cur.fetchone()[0]

            # Top 5 questions that went to Pending in the last 30 days
            cur.execute("""
                SELECT MIN(q.text) AS question, count(DISTINCT q.id) AS asks
                FROM questions q
                JOIN answers a ON a.question_id = q.id AND a.kind = 'fallback'
                WHERE q.clinic_id = %s AND q.asked_at >= now() - interval '30 days'
                GROUP BY lower(q.text)
                ORDER BY asks DESC
                LIMIT 5;
            """, (clinic_id,))
            top_unanswered = format_top_unanswered(cur.fetchall())

            cur.execute("SELECT coalesce(SUM(times_used), 0) FROM lessons WHERE clinic_id = %s;", (clinic_id,))
            total_lessons_used = cur.fetchone()[0]

    # Process weekly ratings into chart-ready structures
    weeks_map: Dict[str, Dict[str, int]] = {}
    for wk, val, cnt in rating_rows:
        if wk not in weeks_map:
            weeks_map[wk] = {"good": 0, "bad": 0, "lessons_used": 0}
        weeks_map[wk][val] = cnt

    for wk, cnt in lesson_rows:
        if wk not in weeks_map:
            weeks_map[wk] = {"good": 0, "bad": 0, "lessons_used": 0}
        weeks_map[wk]["lessons_used"] = cnt

    weekly_data = []
    for wk in sorted(weeks_map.keys()):
        g = weeks_map[wk]["good"]
        b = weeks_map[wk]["bad"]
        total = g + b
        good_share = (g / total * 100.0) if total > 0 else 0.0
        weekly_data.append({
            "week": wk,
            "good": g,
            "bad": b,
            "lessons_used": weeks_map[wk]["lessons_used"],
            "good_share_pct": round(good_share, 1)
        })

    return {
        "summary": {
            "total_questions": total_questions,
            "total_pending": total_pending,
            "total_good": total_good,
            "total_bad": total_bad,
            "total_lessons": total_lessons,
            "total_lessons_used": total_lessons_used
        },
        "weekly_data": weekly_data,
        "top_unanswered": top_unanswered
    }