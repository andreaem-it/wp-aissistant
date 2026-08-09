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


def test_indefinite_active_tenant_retention_is_an_explicit_safe_policy():
    env = safe_env()
    env["DATA_RETENTION_DAYS"] = "0"
    assert production_warnings(env) == []


@pytest.mark.parametrize("value", ["-1", "invalid"])
def test_invalid_retention_is_reported(value):
    env = safe_env()
    env["DATA_RETENTION_DAYS"] = value
    assert any("DATA_RETENTION_DAYS" in warning for warning in production_warnings(env))


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


def test_partial_vapid_configuration_is_reported():
    env = safe_env()
    env["VAPID_PUBLIC_KEY"] = "public-only"
    assert any("VAPID_PRIVATE_KEY" in warning for warning in production_warnings(env))


def test_eu_ai_guard_accepts_only_regional_mistral_for_both_paths():
    env = safe_env() | {
        "REQUIRE_EU_AI": "true",
        "CHAT_MODEL": "mistral/mistral-small-latest",
        "EMBED_MODEL": "mistral/mistral-embed",
        "LLM_API_BASE": "https://api.eu.mistral.ai/v1",
        "MISTRAL_API_KEY": "configured",
    }
    assert production_warnings(env) == []


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"LLM_API_BASE": "https://api.mistral.ai/v1"}, "approved HTTPS EU"),
        ({"CHAT_MODEL": "cloudflare/model"}, "approved EU regional provider"),
        ({"EMBED_MODEL": "cloudflare/embed"}, "approved EU regional provider"),
        ({"MISTRAL_API_KEY": ""}, "MISTRAL_API_KEY"),
    ],
)
def test_eu_ai_guard_fails_closed(overrides, expected):
    env = safe_env() | {
        "REQUIRE_EU_AI": "true",
        "CHAT_MODEL": "mistral/mistral-small-latest",
        "EMBED_MODEL": "mistral/mistral-embed",
        "LLM_API_BASE": "https://api.eu.mistral.ai/v1",
        "MISTRAL_API_KEY": "configured",
    } | overrides
    assert any(expected in warning for warning in production_warnings(env))
