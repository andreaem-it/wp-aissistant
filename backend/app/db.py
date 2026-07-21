import os
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlmodel import SQLModel, Field, create_engine, Session, Column

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://rag:rag@localhost:5432/rag")
EMBED_DIM = int(os.getenv("EMBED_DIM", "768"))  # nomic-embed-text default

engine = create_engine(DATABASE_URL)


class Client(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    api_key: str = Field(index=True, unique=True)


class Chunk(SQLModel, table=True):
    """One embedded piece of content, from an uploaded doc or a synced site page."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    source: str  # "document" | "site"
    source_ref: str  # filename or URL
    text: str
    embedding: list[float] = Field(sa_column=Column(Vector(EMBED_DIM)))


class Product(SQLModel, table=True):
    """Structured WooCommerce product, kept separate from Chunk so the widget can render a card."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    product_url: str = Field(index=True)
    title: str
    price: str = ""
    image_url: str = ""
    embedding: list[float] = Field(sa_column=Column(Vector(EMBED_DIM)))


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    visitor_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "open"  # open | escalated | closed


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    role: str  # user | assistant | operator
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(index=True, foreign_key="conversation.id")
    reason: str
    status: str = "open"  # open | answered | closed
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Operator(SQLModel, table=True):
    """A human agent who logs into the panel. Belongs to one client (tenant)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    client_id: int = Field(index=True, foreign_key="client.id")
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OperatorSession(SQLModel, table=True):
    """Opaque bearer token issued at login; deleted on logout. client_id is denormalized
    here so request scoping doesn't need an extra Operator lookup."""
    id: Optional[int] = Field(default=None, primary_key=True)
    operator_id: int = Field(index=True, foreign_key="operator.id")
    client_id: int = Field(index=True, foreign_key="client.id")
    token: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


def init_db():
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
