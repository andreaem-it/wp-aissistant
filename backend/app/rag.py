from io import BytesIO

from pypdf import PdfReader
from PIL import Image
import pytesseract
from sqlmodel import Session, select
from sqlalchemy import text as sql_text

from .db import Chunk, Product
from .llm import embed

CHUNK_SIZE = 800  # chars; ponytail: naive fixed-size split, switch to sentence-aware chunking if quality suffers
PRODUCT_MAX_DISTANCE = 0.6  # ponytail: cosine distance cutoff so unrelated queries don't surface random products


def extract_text(filename: str, data: bytes) -> str:
    if filename.lower().endswith(".pdf"):
        reader = PdfReader(BytesIO(data))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if filename.lower().endswith((".png", ".jpg", ".jpeg")):
        return pytesseract.image_to_string(Image.open(BytesIO(data)))
    return data.decode("utf-8", errors="ignore")


def chunk_text(text: str, size: int = CHUNK_SIZE) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size) if text[i : i + size].strip()]


def ingest(session: Session, client_id: int, source: str, source_ref: str, text: str):
    for piece in chunk_text(text):
        session.add(Chunk(client_id=client_id, source=source, source_ref=source_ref, text=piece, embedding=embed(piece)))
    session.commit()


def retrieve(session: Session, client_id: int, query: str, k: int = 5) -> list[str]:
    qvec = embed(query)
    rows = session.exec(
        select(Chunk.text)
        .where(Chunk.client_id == client_id)
        .order_by(Chunk.embedding.cosine_distance(qvec))
        .limit(k)
    ).all()
    return list(rows)


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
