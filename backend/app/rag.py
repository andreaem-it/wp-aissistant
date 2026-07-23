import os
import re
from io import BytesIO

from pypdf import PdfReader
from PIL import Image
import pytesseract
from sqlmodel import Session, select
from sqlalchemy import text as sql_text

from .db import Chunk, Product
from .llm import embed

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))  # chars, soft cap per chunk
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))  # chars carried into the next chunk
# cosine distance cutoffs so unrelated queries don't drag in random chunks/products;
# tune per deployment — chunks are noisier text so their cutoff is looser than products'
CHUNK_MAX_DISTANCE = float(os.getenv("CHUNK_MAX_DISTANCE", "0.8"))
PRODUCT_MAX_DISTANCE = float(os.getenv("PRODUCT_MAX_DISTANCE", "0.6"))

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return pytesseract.image_to_string(Image.open(BytesIO(data)))
    return data.decode("utf-8", errors="ignore")


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Pack whole sentences into ~size-char chunks instead of cutting mid-sentence, and
    carry the trailing `overlap` chars of each chunk into the next one so a fact split
    across the boundary still appears whole in at least one chunk."""
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    if not sentences:
        return []

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # a single sentence longer than `size` becomes its own chunk rather than being cut
        if current and len(current) + 1 + len(sentence) > size:
            chunks.append(current)
            current = current[-overlap:].lstrip() if overlap else ""
        current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def ingest(session: Session, client_id: int, source: str, source_ref: str, text: str):
    for piece in chunk_text(text):
        session.add(Chunk(client_id=client_id, source=source, source_ref=source_ref, text=piece, embedding=embed(piece)))
    session.commit()


def retrieve(session: Session, client_id: int, query: str, k: int = 5) -> list[str]:
    qvec = embed(query)
    distance = Chunk.embedding.cosine_distance(qvec)
    rows = session.exec(
        select(Chunk.text, distance.label("distance"))
        .where(Chunk.client_id == client_id)
        .order_by(distance)
        .limit(k)
    ).all()
    return [text for text, dist in rows if dist < CHUNK_MAX_DISTANCE]


def ingest_product(session: Session, client_id: int, product_url: str, title: str, price: str, image_url: str, text: str):
    existing = session.exec(
        select(Product).where(Product.client_id == client_id, Product.product_url == product_url)
    ).first()
    embedding = embed(text)
    if existing:
        existing.title, existing.price, existing.image_url, existing.embedding = title, price, image_url, embedding
        session.add(existing)
    else:
        session.add(Product(client_id=client_id, product_url=product_url, title=title, price=price, image_url=image_url, embedding=embedding))
    session.commit()


def retrieve_products(session: Session, client_id: int, query: str, k: int = 3) -> list[dict]:
    qvec = embed(query)
    distance = Product.embedding.cosine_distance(qvec)
    rows = session.exec(
        select(Product, distance.label("distance"))
        .where(Product.client_id == client_id)
        .order_by(distance)
        .limit(k)
    ).all()
    return [
        {"title": p.title, "price": p.price, "image_url": p.image_url, "product_url": p.product_url}
        for p, dist in rows
        if dist < PRODUCT_MAX_DISTANCE
    ]
