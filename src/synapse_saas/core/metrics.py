"""Prometheus metrics registry.

One process-wide registry; the /metrics endpoint exposes it. Business counters
are incremented from services/middleware — keep cardinality bounded: label on
route *template* (not raw path), status class, and fixed enums only. Never on
org ids, emails, or keys.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

REGISTRY = CollectorRegistry()

# ── HTTP ──────────────────────────────────────────────────────────────────────

HTTP_REQUESTS = Counter(
    "synapse_http_requests_total",
    "HTTP requests handled",
    labelnames=("method", "route", "status_class"),
    registry=REGISTRY,
)

HTTP_LATENCY = Histogram(
    "synapse_http_request_duration_seconds",
    "HTTP request latency",
    labelnames=("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ── Auth ──────────────────────────────────────────────────────────────────────

AUTH_EVENTS = Counter(
    "synapse_auth_events_total",
    "Authentication events",
    labelnames=("event",),  # login_succeeded | login_failed | register | refresh | rate_limited
    registry=REGISTRY,
)

API_KEY_AUTH = Counter(
    "synapse_api_key_auth_total",
    "API-key authenticated requests",
    labelnames=("outcome",),  # ok | invalid
    registry=REGISTRY,
)

# ── Business ──────────────────────────────────────────────────────────────────

BUSINESS_EVENTS = Counter(
    "synapse_business_events_total",
    "Domain events",
    labelnames=("event",),  # org_created | member_invited | plan_changed | trial_started …
    registry=REGISTRY,
)

USAGE_LIMITED = Counter(
    "synapse_usage_limited_total",
    "Requests rejected for exceeding plan limits (402)",
    labelnames=("metric",),
    registry=REGISTRY,
)

FEATURE_GATED = Counter(
    "synapse_feature_gated_total",
    "Requests denied by feature gates (403 feature_not_entitled)",
    labelnames=("feature",),
    registry=REGISTRY,
)

# ── Outbound ──────────────────────────────────────────────────────────────────

WEBHOOK_DELIVERIES = Counter(
    "synapse_webhook_deliveries_total",
    "Outbound webhook delivery attempts",
    labelnames=("outcome",),  # delivered | failed | exhausted
    registry=REGISTRY,
)

EMAILS = Counter(
    "synapse_emails_total",
    "Emails dispatched through the notifier",
    labelnames=("outcome",),  # sent | suppressed | failed
    registry=REGISTRY,
)

# ── Worker ────────────────────────────────────────────────────────────────────

WORKER_JOBS = Counter(
    "synapse_worker_jobs_total",
    "Worker job executions",
    labelnames=("job", "outcome"),  # outcome: ok | error
    registry=REGISTRY,
)

WORKER_JOB_LATENCY = Histogram(
    "synapse_worker_job_duration_seconds",
    "Worker job duration",
    labelnames=("job",),
    buckets=(0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0),
    registry=REGISTRY,
)

# ── Infrastructure ────────────────────────────────────────────────────────────

DB_POOL_CONNECTIONS = Gauge(
    "synapse_db_pool_connections",
    "Database pool connections",
    labelnames=("state",),  # checked_in | checked_out | overflow
    registry=REGISTRY,
)

PROCESS_INFO = Gauge(
    "synapse_process_start_time_seconds",
    "Process start time",
    registry=REGISTRY,
)


def status_class(status: int) -> str:
    """Collapse statuses to bounded classes: 2xx/3xx/4xx/5xx."""
    return f"{status // 100}xx"


def record_http(method: str, route: str, status: int, duration: float) -> None:
    """Record one request. `route` must be the path template, not the raw path."""
    cls = status_class(status)
    HTTP_REQUESTS.labels(method=method, route=route, status_class=cls).inc()
    HTTP_LATENCY.labels(method=method, route=route).observe(duration)


def record_pool() -> None:
    """Snapshot SQLAlchemy async pool gauges (cheap; called from /metrics).

    QueuePool exposes checkedin/checkedout; overflow lives on the async
    wrapper — read both defensively through Any (the sync pool's type stubs
    don't advertise these).
    """
    from typing import Any

    from synapse_saas.core.db import get_engine

    pool: Any = get_engine().pool
    DB_POOL_CONNECTIONS.labels(state="checked_in").set(pool.checkedin())
    DB_POOL_CONNECTIONS.labels(state="checked_out").set(pool.checkedout())
    DB_POOL_CONNECTIONS.labels(state="overflow").set(pool.overflow())
