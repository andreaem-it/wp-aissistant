from app import db
from sqlmodel import Session


def test_onboarding_status_is_derived_from_real_tenant_state(client, tenant):
    initial = client.get("/onboarding/status", headers=tenant["op"])
    assert initial.status_code == 200
    data = initial.json()
    assert data["complete"] is False
    assert {step["key"]: step["complete"] for step in data["steps"]} == {
        "account": True,
        "billing": True,
        "origin": False,
        "knowledge": False,
        "chat": False,
    }

    client.post(
        f"/admin/clients/{tenant['cid']}/origins",
        headers={"Authorization": "Bearer test-admin"},
        json={"allowed_origins": "https://shop.example.test"},
    )
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "onboarding", "message": "ciao"})
    with Session(db.engine) as session:
        session.add(db.Chunk(
            client_id=tenant["cid"],
            source="site",
            source_ref="https://shop.example.test/faq",
            text="FAQ",
            embedding=[0.0] * db.EMBED_DIM,
        ))
        session.commit()

    completed = client.get("/onboarding/status", headers=tenant["op"]).json()
    assert completed["complete"] is True
    assert completed["completed_steps"] == completed["total_steps"] == 5
