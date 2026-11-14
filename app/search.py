import logging
from typing import List, Dict, Any, Optional, Tuple
from app.db import tenant_tx
from app.embeddings import get_single_embedding
from app.config import settings

logger = logging.getLogger("clinic_faq.search")

def search_lessons(clinic_id: str, question: str) -> Optional[Dict[str, Any]]:
    """
    Finds the closest enabled lesson by cosine similarity.
    Returns lesson dict if similarity >= LESSON_THRESHOLD, else None.
    """
    embedding = get_single_embedding(question)
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, question_text, correct_answer, comment, 1 - (embedding <=> %s::vector) AS sim
                FROM lessons
                WHERE enabled = true AND embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 1;
            """, (embedding, embedding))
            row = cur.fetchone()
            if row:
                lesson_id, q_text, correct_ans, comment, sim = row
                if sim is not None and sim >= settings.LESSON_THRESHOLD:
                    return {
                        "id": str(lesson_id),
                        "question_text": q_text,
                        "correct_answer": correct_ans,
                        "comment": comment,
                        "similarity": float(sim)
                    }
    return None

def hybrid_search(clinic_id: str, question: str, top_k: int = 5) -> Tuple[List[Dict[str, Any]], float]:
    """
    Runs vector search and full-text keyword search, fusing them via Reciprocal Rank Fusion (RRF).
    Returns (fused_chunks, best_vector_similarity).
    """
    query_emb = get_single_embedding(question)
    
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            # 1. Vector Search
            cur.execute("""
                SELECT c.id, c.item_id, c.content, 1 - (c.embedding <=> %s::vector) AS sim, k.title
                FROM knowledge_chunks c
                JOIN knowledge_items k ON c.item_id = k.id
                WHERE c.embedding IS NOT NULL
                ORDER BY c.embedding <=> %s::vector
                LIMIT 20;
            """, (query_emb, query_emb))
            vector_rows = cur.fetchall()
            
            # 2. Keyword Search
            cur.execute("""
                SELECT c.id, c.item_id, c.content, ts_rank(c.tsv, websearch_to_tsquery('english', %s)) AS rank, k.title
                FROM knowledge_chunks c
                JOIN knowledge_items k ON c.item_id = k.id
                WHERE c.tsv @@ websearch_to_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT 20;
            """, (question, question))
            keyword_rows = cur.fetchall()
            
    best_similarity = float(vector_rows[0][3]) if vector_rows and vector_rows[0][3] is not None else 0.0

    # Reciprocal Rank Fusion
    rrf_scores: Dict[str, float] = {}
    chunk_data: Dict[str, Dict[str, Any]] = {}
    
    for rank_idx, row in enumerate(vector_rows):
        cid = str(row[0])
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank_idx + 1))
        if cid not in chunk_data:
            chunk_data[cid] = {
                "id": cid,
                "item_id": str(row[1]),
                "content": row[2],
                "vector_sim": float(row[3]) if row[3] is not None else 0.0,
                "title": row[4]
            }

    for rank_idx, row in enumerate(keyword_rows):
        cid = str(row[0])
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (60.0 + rank_idx + 1))
        if cid not in chunk_data:
            chunk_data[cid] = {
                "id": cid,
                "item_id": str(row[1]),
                "content": row[2],
                "vector_sim": 0.0,
                "title": row[4]
            }

    # Sort by RRF score descending
    sorted_chunk_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
    top_chunks = [chunk_data[cid] for cid in sorted_chunk_ids[:top_k]]
    
    return top_chunks, best_similarity
