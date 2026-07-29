"""Public authentication endpoints share an abuse limiter."""
from app import main
from app.ratelimit import FixedWindowLimiter


def test_login_is_rate_limited_per_identity_and_ip(client, tenant, monkeypatch):
    monkeypatch.setattr(main, "auth_limiter", FixedWindowLimiter(2, 60))
    payload = {"email": "op@acme.it", "password": "wrong"}
    assert client.post("/operator/login", json=payload).status_code == 401
    assert client.post("/operator/login", json=payload).status_code == 401
    response = client.post("/operator/login", json=payload)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


def test_forgot_password_is_rate_limited_without_email_enumeration(client, monkeypatch):
    monkeypatch.setattr(main, "auth_limiter", FixedWindowLimiter(1, 60))
    payload = {"email": "unknown@example.test"}
    assert client.post("/auth/forgot", json=payload).status_code == 200
    assert client.post("/auth/forgot", json=payload).status_code == 429
