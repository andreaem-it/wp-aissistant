"""Monthly chat-message quota: usage endpoint + enforcement on /chat."""
from sqlmodel import Session, select

from app import db

ADMIN = {"Authorization": "Bearer test-admin"}


def _set_plan_limit(client, tenant, limit):
    """Point the tenant's client at a plan with the given monthly message limit."""
    plan = client.post("/admin/plans", headers=ADMIN,
                       json={"name": f"Limited{limit}", "price_cents": 900, "monthly_message_limit": limit}).json()
    client.post(f"/admin/clients/{tenant['cid']}/plan", headers=ADMIN, json={"plan_id": plan["id"]})
    return plan


def test_usage_reports_used_and_remaining(client, tenant):
    _set_plan_limit(client, tenant, 5)
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"})
    u = client.get("/usage", headers=tenant["key"]).json()
    assert u["limit"] == 5
    assert u["used"] == 1
    assert u["remaining"] == 4


def test_chat_blocked_over_quota(client, tenant):
    _set_plan_limit(client, tenant, 2)
    # first two messages are answered
    assert client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()["status"] == "open"
    assert client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ancora"}).json()["status"] == "open"
    # the third exceeds the quota
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "terzo"}).json()
    assert r["status"] == "quota_exceeded"
    assert r["reply"] is None


def test_keyword_escalation_still_works_over_quota(client, tenant):
    _set_plan_limit(client, tenant, 1)
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"})  # uses the 1 msg
    # a human-handoff keyword must still reach an operator even over the AI quota
    r = client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "vorrei un rimborso"}).json()
    assert r["status"] == "escalated"


def test_unlimited_plan_never_blocks(client, tenant):
    _set_plan_limit(client, tenant, 0)  # 0 = unlimited
    for _ in range(3):
        assert client.post("/chat", headers=tenant["key"], json={"visitor_id": "v", "message": "ciao"}).json()["status"] == "open"
    u = client.get("/usage", headers=tenant["key"]).json()
    assert u["remaining"] is None
