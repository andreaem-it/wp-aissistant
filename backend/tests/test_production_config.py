import pytest

from app.production_config import enforce_production_config, production_warnings


def safe_env():
    return {
        "ADMIN_API_KEY": "a" * 32,
        "CORS_ALLOW_ALL": "false",
        "PANEL_ORIGINS": "https://panel.example.test",
        "DOCS_ENABLED": "false",
        "DB_AUTO_CREATE": "false",
        "REDIS_URL": "redis://redis:6379/0",
        "DATA_RETENTION_DAYS": "30",
        "METRICS_TOKEN": "m" * 32,
        "EMAIL_PROVIDER": "brevo_api",
        "BREVO_API_KEY": "configured",
    }


def test_safe_production_config_has_no_warnings():
    assert production_warnings(safe_env()) == []


def test_production_config_detects_dangerous_defaults():
    warnings = production_warnings({"ADMIN_API_KEY": "change-me", "CORS_ALLOW_ALL": "true"})
    assert any("ADMIN_API_KEY" in warning for warning in warnings)
    assert any("CORS_ALLOW_ALL" in warning for warning in warnings)
    assert any("DATA_RETENTION_DAYS" in warning for warning in warnings)


def test_strict_mode_fails_closed():
    env = safe_env()
    env["STRICT_PRODUCTION_CONFIG"] = "true"
    env["CORS_ALLOW_ALL"] = "true"
    with pytest.raises(RuntimeError, match="Unsafe production configuration"):
        enforce_production_config(env)


def test_stripe_requires_webhook_secret():
    env = safe_env()
    env["STRIPE_SECRET_KEY"] = "sk_live_example"
    assert any("STRIPE_WEBHOOK_SECRET" in warning for warning in production_warnings(env))
