"""Structured (JSON) logging, stdlib only.

Every log line is one JSON object with at least `timestamp`, `level`, `logger`, `message`.
The current request_id (set by the middleware in main.py) is attached automatically via
a logging.Filter, so grepping logs by request_id ties together everything one HTTP call
produced — including calls made from worker threads that started during that request.
"""

import json
import logging
import os
import sys
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # keep uvicorn's own access log (has method/path/status already); avoid double formatting noise
    logging.getLogger("uvicorn.access").propagate = False


def log(logger: logging.Logger, level: int, message: str, **fields) -> None:
    """Log with structured extra fields: log(logger, logging.INFO, "chat.escalated", client_id=1, reason="...")."""
    logger.log(level, message, extra={"extra_fields": fields})
