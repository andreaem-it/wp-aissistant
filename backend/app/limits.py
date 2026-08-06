"""Input bounds, in one place.

These caps are what stops a single request from costing unbounded memory, tokens or storage.
They are read from the environment so an operator can tighten them without a deploy, and they
live here because several areas enforce the same ones.
"""
import os

MAX_CHAT_MESSAGE_CHARS = int(os.getenv("MAX_CHAT_MESSAGE_CHARS", "4000"))
MAX_INGEST_TEXT_CHARS = int(os.getenv("MAX_INGEST_TEXT_CHARS", "2000000"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
