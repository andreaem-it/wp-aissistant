"""Production configuration checks that never expose secret values."""

from __future__ import annotations

from collections.abc import Mapping


PLACEHOLDER_SECRETS = {"change-me", "changeme", "secret", "test-admin", "password"}


def production_warnings(env: Mapping[str, str]) -> list[str]:
    warnings: list[str] = []

    admin_key = env.get("ADMIN_API_KEY", "").strip()
    if len(admin_key) < 32 or admin_key.lower() in PLACEHOLDER_SECRETS:
        warnings.append("ADMIN_API_KEY must be a non-placeholder secret of at least 32 characters")
    if env.get("CORS_ALLOW_ALL", "true").lower() != "false":
        warnings.append("CORS_ALLOW_ALL must be false")
    if not env.get("PANEL_ORIGINS", "").strip():
        warnings.append("PANEL_ORIGINS must contain the production panel origin")
    if env.get("DOCS_ENABLED", "false").lower() == "true":
        warnings.append("DOCS_ENABLED must be false")
    if env.get("DB_AUTO_CREATE", "false").lower() == "true":
        warnings.append("DB_AUTO_CREATE must be false; use Alembic migrations")
    if not env.get("REDIS_URL", "").strip():
        warnings.append("REDIS_URL is required for shared rate limiting")
    # Conversation retention and account-closure retention are separate policies. Zero means
    # that an active tenant deliberately keeps its history until it chooses another period;
    # canceled accounts follow the independent 90-day deletion workflow. Only malformed or
    # negative values are unsafe configuration.
    raw_retention = env.get("DATA_RETENTION_DAYS", "0") or "0"
    try:
        retention_days = int(raw_retention)
    except ValueError:
        warnings.append("DATA_RETENTION_DAYS must be a non-negative integer")
    else:
        if retention_days < 0:
            warnings.append("DATA_RETENTION_DAYS must be a non-negative integer")

    metrics_token = env.get("METRICS_TOKEN", "").strip()
    if metrics_token and len(metrics_token) < 32:
        warnings.append("METRICS_TOKEN must be at least 32 characters when enabled")
    stripe_key = env.get("STRIPE_SECRET_KEY", "").strip()
    if stripe_key and not env.get("STRIPE_WEBHOOK_SECRET", "").strip():
        warnings.append("STRIPE_WEBHOOK_SECRET is required when Stripe billing is enabled")

    email_provider = env.get("EMAIL_PROVIDER", "smtp").strip().lower()
    if email_provider == "brevo_api" and not env.get("BREVO_API_KEY", "").strip():
        warnings.append("BREVO_API_KEY is required when EMAIL_PROVIDER=brevo_api")
    if email_provider == "smtp" and not env.get("SMTP_HOST", "").strip():
        warnings.append("SMTP_HOST is required when EMAIL_PROVIDER=smtp")
    vapid = [env.get(name, "").strip() for name in ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT")]
    if any(vapid) and not all(vapid):
        warnings.append("VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_SUBJECT must be configured together")
    return warnings


def enforce_production_config(env: Mapping[str, str]) -> list[str]:
    warnings = production_warnings(env)
    if env.get("STRICT_PRODUCTION_CONFIG", "false").lower() == "true" and warnings:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(warnings))
    return warnings
