import time
import math
import hashlib
import logging
from typing import List
from app.config import settings

logger = logging.getLogger("clinic_faq.embeddings")

def _deterministic_fallback_embedding(text: str, dim: int = 768) -> List[float]:
    """
    Generates a deterministic normalized 768-dimensional vector based on text token hashes.
    Useful for offline testing when GEMINI_API_KEY is not configured.
    """
    vec = [0.0] * dim
    words = text.lower().split()
    if not words:
        words = ["empty"]
    for w in words:
        h = int(hashlib.sha256(w.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        val = ((h >> 8) % 1000) / 1000.0 - 0.5
        vec[idx] += val
        
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    else:
        vec[0] = 1.0
    return vec

def get_embeddings(texts: List[str], max_retries: int = 3) -> List[List[float]]:
    """
    Fetches 768-dimensional embeddings for a list of texts using Gemini API with batching and retry.
    Falls back to deterministic vectors if API key is not set.
    """
    if not texts:
        return []
        
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY.startswith("your_"):
        return [_deterministic_fallback_embedding(t) for t in texts]

    try:
        from google import genai
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        # Batching in chunks of 20
        batch_size = 20
        all_embeddings: List[List[float]] = []
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            for attempt in range(max_retries):
                try:
                    response = client.models.embed_content(
                        model=settings.EMBED_MODEL,
                        contents=batch
                    )
                    # response.embeddings is a list of ContentEmbedding objects
                    for emb in response.embeddings:
                        values = list(emb.values)
                        # Normalize if needed
                        all_embeddings.append(values)
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Failed to generate embeddings after {max_retries} attempts: {e}")
                        # Fallback for remaining items
                        for t in batch:
                            all_embeddings.append(_deterministic_fallback_embedding(t))
                    else:
                        time.sleep(1.0 * (2 ** attempt))
                        
        return all_embeddings
    except Exception as e:
        logger.warning(f"Error initializing Gemini embeddings, using fallback: {e}")
        return [_deterministic_fallback_embedding(t) for t in texts]

def get_single_embedding(text: str) -> List[float]:
    res = get_embeddings([text])
    return res[0] if res else _deterministic_fallback_embedding(text)
