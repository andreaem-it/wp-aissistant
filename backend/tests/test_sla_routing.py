"""SLA policies, deadlines and round-robin routing.

The SLA clock starts on escalation, so every test drives a conversation through the
escalation keyword the LLM stub can't bypass.
"""
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app import db, main


ADMIN = {"Authorization": "Bearer test-admin"}


def _escalated_conversation(client, tenant, visitor="sla"):
    """A conversation that reached an operator: "rimborso" is an always-escalate keyword."""
    body = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "vorrei un rimborso"}
    ).json()
    assert body["status"] == "escalated"
    return body["conversation_id"]


def _policy(client, tenant, **overrides):
    payload = {"name": "Standard", "first_response_minutes": 30, "resolution_minutes": 120}
    payload.update(overrides)
    return client.post("/sla-policies", headers=tenant["op"], json=payload).json()


def _conv(conversation_id):
    with Session(db.engine) as session:
        return session.get(db.Conversation, conversation_id)


def _shift_deadlines(conversation_id, minutes):
    """Move a conversation's SLA into the past without waiting for real time to pass."""
    with Session(db.engine) as session:
        conv = session.get(db.Conversation, conversation_id)
        delta = timedelta(minutes=minutes)
        conv.sla_started_at -= delta
        if conv.first_response_due_at:
            conv.first_response_due_at -= delta
            conv.first_response_warn_at -= delta
        if conv.resolution_due_at:
            conv.resolution_due_at -= delta
            conv.resolution_warn_at -= delta
        session.add(conv)
        session.commit()


def test_sla_starts_on_escalation_and_shows_deadlines(client, tenant):
    _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)

    rows = client.get("/conversations", headers=tenant["op"]).json()
    row = next(r for r in rows if r["conversation"]["id"] == conv_id)
    assert row["sla"]["state"] == "ok"
    assert row["sla"]["first_response"]["due_at"] is not None
    assert row["sla"]["first_response"]["met_at"] is None
    assert row["sla"]["resolution"]["due_at"] is not None


def test_support_schedule_is_tenant_scoped_and_recomputes_running_sla(client, tenant):
    _policy(client, tenant, first_response_minutes=120)
    conv_id = _escalated_conversation(client, tenant, visitor="business-hours")
    before = _conv(conv_id).first_response_due_at
    response = client.put("/support-schedule", headers=tenant["op"], json={
        "enabled": True, "weekdays": [1, 2, 3, 4, 5], "start_time": "09:00",
        "end_time": "18:00", "timezone": "Europe/Rome",
    })
    assert response.status_code == 200
    assert response.json()["weekdays"] == [1, 2, 3, 4, 5]
    assert _conv(conv_id).first_response_due_at >= before
    other = _other_tenant(client, "Schedule Other")
    assert client.get("/support-schedule", headers=other["op"]).json()["enabled"] is False
    assert client.get("/support-schedule", headers=tenant["key"]).status_code == 401


def test_support_schedule_rejects_invalid_calendar(client, tenant):
    base = {"enabled": True, "weekdays": [1], "start_time": "09:00", "end_time": "18:00", "timezone": "Europe/Rome"}
    assert client.put("/support-schedule", headers=tenant["op"], json={**base, "weekdays": []}).status_code == 400
    assert client.put("/support-schedule", headers=tenant["op"], json={**base, "timezone": "invalid"}).status_code == 400
    assert client.put("/support-schedule", headers=tenant["op"], json={**base, "end_time": "09:00"}).status_code == 400


def test_conversation_without_policy_has_no_sla(client, tenant):
    conv_id = _escalated_conversation(client, tenant)
    rows = client.get("/conversations", headers=tenant["op"]).json()
    row = next(r for r in rows if r["conversation"]["id"] == conv_id)
    assert row["sla"] is None


def test_sla_states_and_filters(client, tenant):
    _policy(client, tenant, first_response_minutes=60, resolution_minutes=600)
    conv_id = _escalated_conversation(client, tenant)

    # 55 of the 60 minutes elapsed: past the 80% warning threshold, deadline not yet missed
    _shift_deadlines(conv_id, 55)
    rows = client.get("/conversations", headers=tenant["op"], params={"sla_state": "in_scadenza"}).json()
    assert [r["conversation"]["id"] for r in rows] == [conv_id]
    assert rows[0]["sla"]["first_response"]["state"] == "in_scadenza"
    assert client.get("/conversations", headers=tenant["op"], params={"sla_state": "ok"}).json() == []

    # past the deadline
    _shift_deadlines(conv_id, 10)
    rows = client.get("/conversations", headers=tenant["op"], params={"sla_state": "violato"}).json()
    assert [r["conversation"]["id"] for r in rows] == [conv_id]
    assert rows[0]["sla"]["state"] == "violato"

    assert client.get(
        "/conversations", headers=tenant["op"], params={"sla_state": "bogus"}
    ).status_code == 400


def test_operator_reply_meets_first_response_target(client, tenant):
    _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)
    client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "Eccomi"})

    rows = client.get("/conversations", headers=tenant["op"]).json()
    row = next(r for r in rows if r["conversation"]["id"] == conv_id)
    assert row["sla"]["first_response"]["met_at"] is not None
    assert row["sla"]["first_response"]["state"] == "ok"
    assert _conv(conv_id).first_response_at is not None


def test_first_response_is_stamped_once(client, tenant):
    _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)
    client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "prima"})
    first = _conv(conv_id).first_response_at
    client.post(f"/conversations/{conv_id}/reply", headers=tenant["op"], json={"reply": "seconda"})
    assert _conv(conv_id).first_response_at == first


def test_closing_meets_resolution_target(client, tenant):
    _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)
    client.post(f"/conversations/{conv_id}/status", headers=tenant["op"], json={"status": "closed"})

    rows = client.get("/conversations", headers=tenant["op"]).json()
    row = next(r for r in rows if r["conversation"]["id"] == conv_id)
    assert row["sla"]["resolution"]["state"] == "ok"
    assert row["sla"]["resolution"]["met_at"] is not None


def test_most_specific_policy_wins_and_follows_priority(client, tenant):
    generic = _policy(client, tenant, name="Generico", first_response_minutes=600)
    urgent = _policy(client, tenant, name="Urgenti", priority="urgent", first_response_minutes=15)
    conv_id = _escalated_conversation(client, tenant)
    assert _conv(conv_id).sla_policy_id == generic["id"]

    client.patch(f"/conversations/{conv_id}/routing", headers=tenant["op"], json={"priority": "urgent"})
    conv = _conv(conv_id)
    assert conv.sla_policy_id == urgent["id"]
    assert conv.first_response_due_at - conv.sla_started_at == timedelta(minutes=15)


def test_department_policy_overrides_generic(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Resi"}).json()
    _policy(client, tenant, name="Generico", first_response_minutes=600)
    dept_policy = _policy(client, tenant, name="Resi", department_id=department["id"], first_response_minutes=20)
    conv_id = _escalated_conversation(client, tenant)

    client.patch(
        f"/conversations/{conv_id}/routing", headers=tenant["op"], json={"department_id": department["id"]}
    )
    assert _conv(conv_id).sla_policy_id == dept_policy["id"]


def test_inactive_policy_is_ignored(client, tenant):
    policy = _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)
    assert _conv(conv_id).sla_policy_id == policy["id"]

    client.patch(f"/sla-policies/{policy['id']}", headers=tenant["op"], json={"active": False})
    conv = _conv(conv_id)
    assert conv.sla_policy_id is None
    assert conv.first_response_due_at is None


def test_deleting_policy_detaches_running_conversations(client, tenant):
    policy = _policy(client, tenant)
    conv_id = _escalated_conversation(client, tenant)
    assert client.delete(f"/sla-policies/{policy['id']}", headers=tenant["op"]).status_code == 200
    conv = _conv(conv_id)
    assert conv.sla_policy_id is None
    assert conv.sla_started_at is not None  # the clock keeps its start, only the targets go away


def test_sla_breach_monitor_alerts_once(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify_sla_breach", lambda *args: sent.append(args))
    _policy(client, tenant, first_response_minutes=30, resolution_minutes=60)
    conv_id = _escalated_conversation(client, tenant)
    _shift_deadlines(conv_id, 31)

    with Session(db.engine) as session:
        assert main.check_sla_breaches(session) == 1
        assert main.check_sla_breaches(session) == 0  # idempotent
    assert [s[2] for s in sent] == ["first_response"]
    assert _conv(conv_id).first_response_breach_notified is True

    with Session(db.engine) as session:
        audit = session.exec(
            select(db.AuditLog).where(db.AuditLog.action == "sla.breach")
        ).all()
    assert len(audit) == 1
    assert audit[0].client_id == tenant["cid"]


def test_round_robin_cycles_through_operators(client, tenant):
    client.post(
        f"/admin/clients/{tenant['cid']}/operators",
        headers=ADMIN,
        json={"email": "rr2@acme.it", "password": "password1"},
    )
    client.put("/routing-settings", headers=tenant["op"], json={"mode": "round_robin"})
    team = client.get("/team/operators", headers=tenant["op"]).json()
    ids = sorted(member["id"] for member in team)
    assert len(ids) == 2

    assigned = []
    for n in range(3):
        conv_id = _escalated_conversation(client, tenant, visitor=f"rr-{n}")
        assigned.append(_conv(conv_id).assigned_operator_id)
    assert assigned == [ids[0], ids[1], ids[0]]


def test_round_robin_uses_department_members_then_falls_back_to_queue(client, tenant):
    other = client.post(
        f"/admin/clients/{tenant['cid']}/operators",
        headers=ADMIN,
        json={"email": "dept@acme.it", "password": "password1"},
    )
    department = client.post("/departments", headers=tenant["op"], json={"name": "Vendite"}).json()
    member_id = next(
        m["id"] for m in client.get("/team/operators", headers=tenant["op"]).json()
        if m["email"] == "dept@acme.it"
    )
    assert other.status_code == 200
    client.post(
        f"/departments/{department['id']}/members", headers=tenant["op"], json={"operator_id": member_id}
    )
    client.put(
        "/routing-settings",
        headers=tenant["op"],
        json={"mode": "round_robin", "fallback_department_id": department["id"]},
    )

    conv_id = _escalated_conversation(client, tenant, visitor="dept-rr")
    conv = _conv(conv_id)
    assert conv.department_id == department["id"]
    assert conv.assigned_operator_id == member_id  # only the department member is eligible

    members = client.get(f"/departments/{department['id']}/members", headers=tenant["op"]).json()
    assert [m["id"] for m in members] == [member_id]

    # emptying the pool leaves the next conversation in the department queue, unassigned
    client.delete(f"/departments/{department['id']}/members/{member_id}", headers=tenant["op"])
    conv2_id = _escalated_conversation(client, tenant, visitor="dept-rr-2")
    conv2 = _conv(conv2_id)
    assert conv2.department_id == department["id"]
    assert conv2.assigned_operator_id is None


def test_routing_off_by_default_leaves_conversation_unassigned(client, tenant):
    conv_id = _escalated_conversation(client, tenant)
    assert _conv(conv_id).assigned_operator_id is None
    assert client.get("/routing-settings", headers=tenant["op"]).json()["mode"] == "off"


def test_sla_stats_report_breaches(client, tenant):
    _policy(client, tenant, first_response_minutes=30, resolution_minutes=60)
    ok_id = _escalated_conversation(client, tenant, visitor="stats-ok")
    breached_id = _escalated_conversation(client, tenant, visitor="stats-ko")
    _shift_deadlines(breached_id, 90)

    stats = client.get("/stats", headers=tenant["op"]).json()["sla"]
    assert stats["tracked"] == 2
    assert stats["breached"] == 1
    assert stats["compliance_rate"] == 0.5
    assert _conv(ok_id).sla_started_at is not None


# ---- tenant isolation ----


def _other_tenant(client, name):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


def test_sla_policies_are_tenant_scoped(client, tenant):
    policy = _policy(client, tenant)
    other = _other_tenant(client, "Sla Other")

    assert client.get("/sla-policies", headers=other["op"]).json() == []
    assert client.patch(
        f"/sla-policies/{policy['id']}", headers=other["op"], json={"name": "hack"}
    ).status_code == 404
    assert client.delete(f"/sla-policies/{policy['id']}", headers=other["op"]).status_code == 404


def test_sla_policy_rejects_cross_tenant_department(client, tenant):
    other = _other_tenant(client, "Dept Other")
    department = client.post("/departments", headers=other["op"], json={"name": "Loro"}).json()
    response = client.post(
        "/sla-policies",
        headers=tenant["op"],
        json={"name": "Furbo", "department_id": department["id"]},
    )
    assert response.status_code == 404


def test_department_members_are_tenant_scoped(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Vendite"}).json()
    other = _other_tenant(client, "Member Other")
    other_operator = client.get(
        f"/admin/clients/{other['cid']}/operators", headers=ADMIN
    ).json()[0]

    assert client.post(
        f"/departments/{department['id']}/members",
        headers=tenant["op"],
        json={"operator_id": other_operator["id"]},
    ).status_code == 404
    assert client.get(
        f"/departments/{department['id']}/members", headers=other["op"]
    ).status_code == 404


def test_routing_settings_are_tenant_scoped(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Vendite"}).json()
    other = _other_tenant(client, "Routing Other")

    client.put("/routing-settings", headers=tenant["op"], json={"mode": "round_robin"})
    assert client.get("/routing-settings", headers=other["op"]).json()["mode"] == "off"
    assert client.put(
        "/routing-settings",
        headers=other["op"],
        json={"mode": "round_robin", "fallback_department_id": department["id"]},
    ).status_code == 404
    assert client.put(
        "/routing-settings", headers=tenant["op"], json={"mode": "chaos"}
    ).status_code == 400


def test_breach_monitor_keeps_tenants_separate(client, tenant, monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify_sla_breach", lambda *args: sent.append(args))
    other = _other_tenant(client, "Breach Other")
    _policy(client, tenant, first_response_minutes=30)
    client.post(
        "/sla-policies",
        headers=other["op"],
        json={"name": "Loro", "first_response_minutes": 30, "resolution_minutes": 120},
    )
    mine = _escalated_conversation(client, tenant, visitor="mine")
    theirs = client.post(
        "/chat",
        headers={"Authorization": f"Bearer {other['api_key']}"},
        json={"visitor_id": "theirs", "message": "vorrei un rimborso"},
    ).json()["conversation_id"]
    _shift_deadlines(mine, 31)

    with Session(db.engine) as session:
        assert main.check_sla_breaches(session) == 1
    assert [s[1] for s in sent] == [mine]
    assert _conv(theirs).first_response_breach_notified is False

    rows = client.get("/conversations", headers=other["op"], params={"sla_state": "violato"}).json()
    assert rows == []


def test_deleting_department_cleans_members_and_policies(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Resi"}).json()
    team = client.get("/team/operators", headers=tenant["op"]).json()
    client.post(
        f"/departments/{department['id']}/members", headers=tenant["op"], json={"operator_id": team[0]["id"]}
    )
    _policy(client, tenant, name="Resi", department_id=department["id"], first_response_minutes=10)
    client.put(
        "/routing-settings",
        headers=tenant["op"],
        json={"mode": "round_robin", "fallback_department_id": department["id"]},
    )
    conv_id = _escalated_conversation(client, tenant)

    assert client.delete(f"/departments/{department['id']}", headers=tenant["op"]).status_code == 200
    assert client.get("/sla-policies", headers=tenant["op"]).json() == []
    assert client.get("/routing-settings", headers=tenant["op"]).json()["fallback_department_id"] is None
    conv = _conv(conv_id)
    assert conv.department_id is None
    assert conv.sla_policy_id is None
    with Session(db.engine) as session:
        assert session.exec(select(db.DepartmentMember)).all() == []


def test_sla_view_handles_missing_policy(client, tenant):
    """A conversation escalated before any policy existed reports no SLA, not a broken one."""
    conv_id = _escalated_conversation(client, tenant)
    conv = _conv(conv_id)
    assert conv.sla_started_at is not None
    assert main._sla_view(conv, datetime.utcnow()) is None
