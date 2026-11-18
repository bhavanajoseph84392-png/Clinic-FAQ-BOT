import io
import csv
import logging
from typing import List, Dict, Any, Optional
from pypdf import PdfReader
from app.db import tenant_tx
from app.embeddings import get_embeddings
from app.config import settings

logger = logging.getLogger("clinic_faq.knowledge")

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extracts text from PDF bytes.
    Raises ValueError with specific message if no text found.
    """
    reader = PdfReader(io.BytesIO(file_bytes))
    full_text = []
    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text()
        if text:
            full_text.append(text)
            
    extracted = "\n".join(full_text).strip()
    if not extracted:
        raise ValueError("No text found. Scanned PDFs are not supported yet.")
    return extracted

def chunk_text(title: str, text: str, chunk_size: int = 400, overlap: int = 50) -> List[str]:
    """
    Splits text into chunks of ~300-500 words with 50-word overlap.
    Prefixes each chunk with the item title.
    """
    words = text.split()
    if not words:
        return []
        
    chunks = []
    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size
        
    for i in range(0, len(words), step):
        chunk_words = words[i:i + chunk_size]
        content = f"[{title}]\n" + " ".join(chunk_words)
        chunks.append(content)
        if i + chunk_size >= len(words):
            break
            
    return chunks

def chunk_price_list(title: str, content: str) -> List[str]:
    """
    Parses CSV/tabular price list, keeping the header on every row and never splitting a row.
    """
    lines = [line.strip() for line in content.strip().splitlines() if line.strip()]
    if not lines:
        return []
        
    chunks = []
    # If pipe, comma, or tab separated
    delimiter = "|" if "|" in lines[0] else "," if "," in lines[0] else "\t" if "\t" in lines[0] else None
    
    if delimiter:
        reader = csv.reader(lines, delimiter=delimiter)
        rows = list(reader)
        if not rows:
            return []
        header = " | ".join(c.strip() for c in rows[0] if c.strip())
        for row in rows[1:]:
            cells = [c.strip() for c in row if c.strip()]
            if not cells:
                continue
            row_str = " | ".join(cells)
            chunk = f"[{title}] Price List\nHeader: {header}\nItem: {row_str}"
            chunks.append(chunk)
    else:
        # Plain lines
        header = lines[0]
        for line in lines[1:]:
            chunk = f"[{title}]\nHeader: {header}\nRow: {line}"
            chunks.append(chunk)
            
    return chunks if chunks else [f"[{title}]\n{content}"]

def process_knowledge_item(clinic_id: str, item_id: str):
    """
    Extracts text, splits into chunks, computes embeddings, and stores in knowledge_chunks.
    Updates item status to 'ready' or 'failed'.
    """
    with tenant_tx(clinic_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, type, title, body, file_name 
                FROM knowledge_items 
                WHERE id = %s AND clinic_id = %s;
            """, (item_id, clinic_id))
            item = cur.fetchone()
            if not item:
                return
                
            item_type = item[1]
            title = item[2]
            body = item[3] or ""
            
            try:
                if item_type == "price_list":
                    chunks = chunk_price_list(title, body)
                else:
                    chunks = chunk_text(title, body)
                    
                if not chunks:
                    raise ValueError("No extractable content in item")
                    
                # Delete old chunks for this item
                cur.execute("DELETE FROM knowledge_chunks WHERE item_id = %s AND clinic_id = %s;", (item_id, clinic_id))
                
                # Generate embeddings
                embeddings = get_embeddings(chunks)
                
                # Insert chunks
                for idx, (chunk_text_content, emb) in enumerate(zip(chunks, embeddings)):
                    cur.execute("""
                        INSERT INTO knowledge_chunks (clinic_id, item_id, chunk_index, content, embedding, embedding_model)
                        VALUES (%s, %s, %s, %s, %s, %s);
                    """, (clinic_id, item_id, idx, chunk_text_content, emb, settings.EMBED_MODEL))
                    
                cur.execute("""
                    UPDATE knowledge_items 
                    SET status = 'ready', error_message = NULL, updated_at = now() 
                    WHERE id = %s AND clinic_id = %s;
                """, (item_id, clinic_id))
            except Exception as e:
                logger.error(f"Failed to process knowledge item {item_id}: {e}")
                cur.execute("""
                    UPDATE knowledge_items 
                    SET status = 'failed', error_message = %s, updated_at = now() 
                    WHERE id = %s AND clinic_id = %s;
                """, (str(e), item_id, clinic_id))
