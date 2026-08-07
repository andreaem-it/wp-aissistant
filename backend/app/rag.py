import logging
import math
import os
import re
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader
from PIL import Image
import pytesseract
from sqlmodel import Session, select
from sqlalchemy import text as sql_text

from . import i18n

from .db import Chunk, EmbeddingUsage, Product
from .llm import EMBED_MODEL, embed
from .logging_config import log

logger = logging.getLogger("wpai.rag")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))  # chars, soft cap per chunk
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "150"))  # chars carried into the next chunk
# cosine distance cutoffs so unrelated queries don't drag in random chunks/products;
# tune per deployment — chunks are noisier text so their cutoff is looser than products'
CHUNK_MAX_DISTANCE = float(os.getenv("CHUNK_MAX_DISTANCE", "0.8"))
# 0.45 (was 0.6): 0.6 was loose enough that greetings/small-talk ("Ciao") dragged in unrelated
# products. Real product queries score well below this; tune per deployment/embedding model.
PRODUCT_MAX_DISTANCE = float(os.getenv("PRODUCT_MAX_DISTANCE", "0.45"))
# reranking: pull a wider candidate pool then use MMR to pick a relevant *and* diverse set,
# so near-duplicate chunks don't crowd out complementary context.
RETRIEVE_FETCH_K = int(os.getenv("RETRIEVE_FETCH_K", "20"))
MMR_LAMBDA = float(os.getenv("MMR_LAMBDA", "0.5"))  # 1.0 = pure relevance, 0.0 = pure diversity

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def mmr_select(query_sims: list[float], embeddings: list[list[float]], k: int, lambda_mult: float) -> list[int]:
    """Maximal Marginal Relevance: greedily pick indices that maximise
    `lambda*sim(query) - (1-lambda)*max sim(already picked)`, trading relevance for diversity.
    Pure function (no DB/LLM) so it can be unit-tested directly."""
    remaining = set(range(len(embeddings)))
    selected: list[int] = []
    while remaining and len(selected) < k:
        if not selected:
            best = max(remaining, key=lambda i: query_sims[i])
        else:
            def mmr_score(i: int) -> float:
                redundancy = max(_cosine(embeddings[i], embeddings[j]) for j in selected)
                return lambda_mult * query_sims[i] - (1.0 - lambda_mult) * redundancy
            best = max(remaining, key=mmr_score)
        selected.append(best)
        remaining.discard(best)
    return selected


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




def record_embedding(session: Session, client_id: int, chars: int, *, kind: str) -> None:
    """Add today's embedded volume to the tenant's rollup.

    Called where the embedding actually happens, so nothing can be embedded without being
    counted. `kind` separates "ingest" (grows with the knowledge base) from "query" (grows with
    traffic): a single total would hide which of the two is driving the bill.

    Best-effort by design: a failure here must never abort an ingest or a visitor's answer, so
    it is logged and swallowed. Under-reporting a cost is bad; refusing to answer is worse.
    """
    if chars <= 0:
        return
    column = "ingest_chars" if kind == "ingest" else "query_chars"
    try:
        today = datetime.utcnow().date()
        row = session.exec(
            select(EmbeddingUsage).where(
                EmbeddingUsage.client_id == client_id,
                EmbeddingUsage.model == EMBED_MODEL,
                EmbeddingUsage.day == today,
            )
        ).first()
        if row is None:
            row = EmbeddingUsage(client_id=client_id, model=EMBED_MODEL, day=today)
        setattr(row, column, getattr(row, column) + chars)
        row.requests += 1
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    except Exception:  # noqa: BLE001 — measuring must never break what it measures
        session.rollback()
        log(logger, logging.WARNING, "embedding.usage_not_recorded", client_id=client_id)


def ingest(session: Session, client_id: int, source: str, source_ref: str, text: str):
    embedded_chars = 0
    for piece in chunk_text(text):
        session.add(Chunk(client_id=client_id, source=source, source_ref=source_ref, text=piece, embedding=embed(piece)))
        embedded_chars += len(piece)
    session.commit()
    record_embedding(session, client_id, embedded_chars, kind="ingest")


def retrieve_with_meta(session: Session, client_id: int, query: str, k: int = 5) -> tuple[list[str], list[dict]]:
    """Like retrieve() but also returns diagnostics for the admin debug view: the surviving
    candidate pool (source_ref + cosine distance) and which chunks the MMR rerank selected.

    Returns (context_texts, meta): context_texts are the k selected chunk texts (what the LLM
    sees); meta is the full candidate list ordered by distance, each entry
    {chunk_id, source, source_ref, distance, selected}."""
    qvec = embed(query)
    record_embedding(session, client_id, len(query or ""), kind="query")
    distance = Chunk.embedding.cosine_distance(qvec)
    rows = session.exec(
        select(Chunk.id, Chunk.source, Chunk.source_ref, Chunk.text, Chunk.embedding, distance.label("distance"))
        .where(Chunk.client_id == client_id)
        .order_by(distance)
        .limit(RETRIEVE_FETCH_K)
    ).all()
    candidates = [
        {"id": cid, "source": src, "source_ref": ref, "text": txt, "emb": list(emb), "distance": float(dist)}
        for cid, src, ref, txt, emb, dist in rows
        if emb is not None and dist < CHUNK_MAX_DISTANCE
    ]
    if not candidates:
        return [], []
    query_sims = [1.0 - c["distance"] for c in candidates]  # pgvector cosine_distance = 1 - sim
    embeddings = [c["emb"] for c in candidates]
    selected_idx = mmr_select(query_sims, embeddings, k, MMR_LAMBDA)
    selected_set = set(selected_idx)
    context = [candidates[i]["text"] for i in selected_idx]
    meta = [
        {
            "chunk_id": c["id"], "source": c["source"], "source_ref": c["source_ref"],
            "distance": round(c["distance"], 4), "selected": i in selected_set,
        }
        for i, c in enumerate(candidates)
    ]
    return context, meta


def retrieve(session: Session, client_id: int, query: str, k: int = 5) -> list[str]:
    """Fetch the top RETRIEVE_FETCH_K chunks by cosine distance, drop off-topic ones
    (CHUNK_MAX_DISTANCE), then MMR-rerank to k relevant-but-diverse chunks."""
    context, _ = retrieve_with_meta(session, client_id, query, k)
    return context


def ingest_product(session: Session, client_id: int, product_url: str, title: str, price: str, image_url: str, text: str):
    existing = session.exec(
        select(Product).where(Product.client_id == client_id, Product.product_url == product_url)
    ).first()
    embedding = embed(text)
    record_embedding(session, client_id, len(text or ""), kind="ingest")
    if existing:
        existing.title, existing.price, existing.image_url, existing.embedding = title, price, image_url, embedding
        session.add(existing)
    else:
        session.add(Product(client_id=client_id, product_url=product_url, title=title, price=price, image_url=image_url, embedding=embedding))
    session.commit()


def retrieve_products(session: Session, client_id: int, query: str, k: int = 3) -> list[dict]:
    qvec = embed(query)
    record_embedding(session, client_id, len(query or ""), kind="query")
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
        if dist is not None and dist < PRODUCT_MAX_DISTANCE  # dist is NULL for not-yet-embedded rows
    ]


# ---- Prompt and scope ------------------------------------------------------------------------
#
# Pure logic shared by the chat endpoint and the evaluation suite in backend/evals: how the
# grounding instruction is built, what counts as small talk, and when the retrieved context is
# too far from the question to be usable. Kept out of the router so an eval never imports one.


SCOPE_MAX_DISTANCE = float(os.getenv("SCOPE_MAX_DISTANCE", "0.62"))


def build_system(context: list[str], language: str | None = None) -> str:
    return (
        "You are a customer support assistant. Handle greetings and small talk yourself, "
        "normally, without calling any tool. For substantive questions, answer only using "
        "the context below. Call escalate_to_human ONLY when: the answer to a substantive "
        "question isn't in the context, or the request needs human authority (refunds, "
        "complaints, account changes). Do not escalate greetings or vague messages — ask "
        "the user to clarify instead. You cannot modify the WooCommerce cart, place orders, "
        "apply coupons, or calculate a new cart total. Never claim that you performed one of "
        "these actions. When a visitor asks to add a product to the cart, tell them to use the "
        "\"Aggiungi al carrello\" button on the product card; only the site can confirm that "
        "the operation succeeded.\n\nContext:\n" + "\n---\n".join(context)
        + i18n.prompt_language_instruction(language)
    )


_SMALL_TALK_RE = re.compile(
    r"^\s*(?:ciao|salve|buongiorno|buonasera|hey|hello|hi|grazie|thanks|"
    r"arrivederci|a presto|come stai|chi sei|cosa (?:sai|puoi) fare)[!?.\s]*$",
    re.IGNORECASE,
)


def is_small_talk(message: str) -> bool:
    return bool(_SMALL_TALK_RE.match(message or ""))


def retrieval_is_in_scope(retrieval_meta: list[dict]) -> bool:
    """Require semantic evidence from this tenant's own knowledge base."""
    return any(
        item.get("selected") and float(item.get("distance", 1.0)) <= SCOPE_MAX_DISTANCE
        for item in retrieval_meta
    )
