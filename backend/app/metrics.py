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
sla_breaches_total = Counter(
    "wpai_sla_breaches_total",
    "SLA targets breached (counted once per conversation and target)",
    ["target"],  # first_response | resolution
)

# Copertura della licenza sulle chiamate del widget, contata **senza rifiutare nulla**: è il
# numero che dice quando si può applicare il vincolo senza spegnere qualcuno, e quanto traffico
# arriva senza header Origin — cioè non da un browser, dove il binding oggi non si applica.
widget_origin_checks_total = Counter(
    "wpai_widget_origin_checks_total",
    "Widget calls classified by licence coverage (observation only, nothing is rejected)",
    ["result"],  # covered | uncovered | missing_origin
)
