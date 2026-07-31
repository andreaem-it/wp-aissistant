from app import db
from sqlmodel import Session


ADMIN = {"Authorization": "Bearer test-admin"}


def _conversation(client, tenant, visitor="routing"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "ciao"}
    ).json()["conversation_id"]


def test_department_assignment_priority_and_filters(client, tenant):
    conv_id = _conversation(client, tenant)
    department = client.post(
        "/departments", headers=tenant["op"], json={"name": "Vendite"}
    ).json()
    team = client.get("/team/operators", headers=tenant["op"]).json()
    operator_id = team[0]["id"]

    updated = client.patch(
        f"/conversations/{conv_id}/routing",
        headers=tenant["op"],
        json={
            "priority": "urgent",
            "assigned_operator_id": operator_id,
            "department_id": department["id"],
        },
    )
    assert updated.status_code == 200

    rows = client.get(
        "/conversations",
        headers=tenant["op"],
        params={"priority": "urgent", "department_id": department["id"], "assigned_operator_id": operator_id},
    ).json()
    assert len(rows) == 1
    assert rows[0]["conversation"]["id"] == conv_id
    assert rows[0]["conversation"]["priority"] == "urgent"
    assert rows[0]["assignee"]["id"] == operator_id
    assert rows[0]["department"]["name"] == "Vendite"

    client.patch(
        f"/conversations/{conv_id}/routing",
        headers=tenant["op"],
        json={"clear_assignee": True, "clear_department": True},
    )
    unassigned = client.get("/conversations", headers=tenant["op"], params={"unassigned": True}).json()
    assert any(row["conversation"]["id"] == conv_id for row in unassigned)


def test_routing_rejects_cross_tenant_entities(client, tenant):
    conv_id = _conversation(client, tenant)
    other = client.post("/admin/clients", headers=ADMIN, json={"name": "Other Routing"}).json()
    client.post(
        f"/admin/clients/{other['id']}/operators",
        headers=ADMIN,
        json={"email": "routing-other@x.it", "password": "password1"},
    )
    other_operator = client.get(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN
    ).json()[0]
    response = client.patch(
        f"/conversations/{conv_id}/routing",
        headers=tenant["op"],
        json={"assigned_operator_id": other_operator["id"]},
    )
    assert response.status_code == 404


def test_deleting_department_unassigns_conversations(client, tenant):
    conv_id = _conversation(client, tenant)
    department = client.post("/departments", headers=tenant["op"], json={"name": "Resi"}).json()
    client.patch(
        f"/conversations/{conv_id}/routing",
        headers=tenant["op"],
        json={"department_id": department["id"]},
    )
    assert client.delete(f"/departments/{department['id']}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.get(db.Conversation, conv_id).department_id is None
