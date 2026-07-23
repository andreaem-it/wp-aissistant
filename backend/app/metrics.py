"""Prometheus metrics. Exposed at GET /metrics (see main.py).

Kept dependency-light: the prometheus_client default registry, no multiprocess mode.
With several uvicorn workers each process exposes its own counters — scrape per replica
or aggregate at the collector, as usual for Prometheus.
"""

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "wpai_http_requests_total",
    "HTTP requests processed",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "wpai_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

chat_messages_total = Counter(
    "wpai_chat_messages_total", "Visitor chat messages processed"
)
escalations_total = Counter(
    "wpai_escalations_total", "Conversations escalated to a human", ["trigger"]
)
ingest_jobs_total = Counter(
    "wpai_ingest_jobs_total", "Ingest jobs finished", ["status"]
)
