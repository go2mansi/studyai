import io
from pathlib import Path
from pypdf import PdfReader

CHUNK_SIZE = 1400
CHUNK_OVERLAP = 220
MAX_CHUNKS = 600  # keeps one upload from filling the database
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}

def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ValueError("This PDF is password-protected.")
        except ValueError:
            raise
        except Exception:
            raise ValueError("This PDF could not be read. It may be corrupted.")
        pages = []
        for i, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i}]\n{text}")
        return "\n\n".join(pages)
    if ext in {".txt", ".md"}:
        return data.decode("utf-8", errors="ignore")
    raise ValueError("Only PDF, TXT and Markdown files are supported.")

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP):
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if len(chunks) >= MAX_CHUNKS:
            break
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks
