"""Saved inbox views: ownership, sharing, tenant isolation and inbox ordering."""
from conftest import TENANT_ORIGIN

ADMIN = {"Authorization": "Bearer test-admin"}


def _second_operator(client, tenant, email="colleague@acme.it"):
    client.post(
        f"/admin/clients/{tenant['cid']}/operators",
        headers=ADMIN,
        json={"email": email, "password": "password1"},
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _other_tenant(client, name="Views Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name, "allowed_origins": TENANT_ORIGIN}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def test_create_and_list_own_view(client, tenant):
    created = client.post(
        "/saved-views",
        headers=tenant["op"],
        json={"name": "Urgenti aperte", "filters": {"status": "open", "priority": "urgent"}, "sort": "priority"},
    ).json()
    assert created["filters"] == {"status": "open", "priority": "urgent"}
    assert created["sort"] == "priority"
    assert created["shared"] is False

    views = client.get("/saved-views", headers=tenant["op"]).json()
    assert [v["id"] for v in views] == [created["id"]]
    assert views[0]["owner_name"] == "op@acme.it"


def test_personal_view_is_invisible_to_colleagues_until_shared(client, tenant):
    colleague = _second_operator(client, tenant)
    view = client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Mie", "filters": {"unassigned": True}}
    ).json()
    assert client.get("/saved-views", headers=colleague).json() == []

    client.patch(f"/saved-views/{view['id']}", headers=tenant["op"], json={"shared": True})
    shared = client.get("/saved-views", headers=colleague).json()
    assert [v["id"] for v in shared] == [view["id"]]


def test_only_the_owner_can_edit_or_delete_a_shared_view(client, tenant):
    colleague = _second_operator(client, tenant)
    view = client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Condivisa", "shared": True}
    ).json()

    assert client.patch(
        f"/saved-views/{view['id']}", headers=colleague, json={"name": "Rinominata"}
    ).status_code == 403
    assert client.delete(f"/saved-views/{view['id']}", headers=colleague).status_code == 403
    assert client.delete(f"/saved-views/{view['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/saved-views", headers=tenant["op"]).json() == []


def test_views_are_tenant_scoped(client, tenant):
    view = client.post("/saved-views", headers=tenant["op"], json={"name": "Mia", "shared": True}).json()
    other = _other_tenant(client)

    assert client.get("/saved-views", headers=other["op"]).json() == []
    assert client.patch(
        f"/saved-views/{view['id']}", headers=other["op"], json={"name": "hack"}
    ).status_code == 404
    assert client.delete(f"/saved-views/{view['id']}", headers=other["op"]).status_code == 404


def test_view_rejects_cross_tenant_and_unknown_filters(client, tenant):
    other = _other_tenant(client, "Filter Other")
    department = client.post("/departments", headers=other["op"], json={"name": "Loro"}).json()

    assert client.post(
        "/saved-views",
        headers=tenant["op"],
        json={"name": "Furba", "filters": {"department_id": department["id"]}},
    ).status_code == 404
    assert client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Ignota", "filters": {"visitor_id": "x"}}
    ).status_code == 400
    assert client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Stato", "filters": {"status": "bogus"}}
    ).status_code == 400
    assert client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Ordine", "sort": "bogus"}
    ).status_code == 400
    assert client.get("/saved-views", headers=tenant["op"]).json() == []


def test_saved_filters_reproduce_the_inbox_query(client, tenant):
    client.post("/chat", headers=tenant["key"], json={"visitor_id": "v-open", "message": "ciao"})
    escalated = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "v-esc", "message": "vorrei un rimborso"}
    ).json()["conversation_id"]

    view = client.post(
        "/saved-views", headers=tenant["op"], json={"name": "Escalation", "filters": {"status": "escalated"}}
    ).json()
    rows = client.get("/conversations", headers=tenant["op"], params={**view["filters"], "sort": view["sort"]}).json()
    assert [r["conversation"]["id"] for r in rows] == [escalated]


def test_inbox_sort_modes(client, tenant):
    first = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "s1", "message": "ciao"}
    ).json()["conversation_id"]
    second = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "s2", "message": "ciao"}
    ).json()["conversation_id"]
    client.patch(f"/conversations/{first}/routing", headers=tenant["op"], json={"priority": "urgent"})

    def ids(sort):
        return [
            r["conversation"]["id"]
            for r in client.get("/conversations", headers=tenant["op"], params={"sort": sort}).json()
        ]

    assert ids("recent") == [second, first]
    assert ids("oldest") == [first, second]
    assert ids("priority") == [first, second]  # urgent first
    assert client.get("/conversations", headers=tenant["op"], params={"sort": "bogus"}).status_code == 400


def test_sla_sort_puts_the_nearest_deadline_first(client, tenant):
    client.post(
        "/sla-policies",
        headers=tenant["op"],
        json={"name": "Lento", "first_response_minutes": 600, "resolution_minutes": 1200},
    )
    slow = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "slow", "message": "vorrei un rimborso"}
    ).json()["conversation_id"]
    client.post(
        "/sla-policies",
        headers=tenant["op"],
        json={"name": "Veloce", "priority": "urgent", "first_response_minutes": 5, "resolution_minutes": 30},
    )
    fast = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "fast", "message": "vorrei un rimborso"}
    ).json()["conversation_id"]
    client.patch(f"/conversations/{fast}/routing", headers=tenant["op"], json={"priority": "urgent"})
    plain = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "plain", "message": "ciao"}
    ).json()["conversation_id"]

    ids = [
        r["conversation"]["id"]
        for r in client.get("/conversations", headers=tenant["op"], params={"sort": "sla"}).json()
    ]
    assert ids[:2] == [fast, slow]
    assert ids[-1] == plain  # no SLA running: last
