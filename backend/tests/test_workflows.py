"""No-code automations: matching, actions, isolation, run log and loop protection."""
import json
from datetime import timedelta

from sqlmodel import Session, select

from app import db, tagging, webhooks, workflows


ADMIN = {"Authorization": "Bearer test-admin"}


def _workflow(client, tenant, **overrides):
    payload = {
        "name": "Regola",
        "trigger": "conversation.escalated",
        "conditions": [],
        "actions": [{"type": "set_priority", "value": "urgent"}],
    }
    payload.update(overrides)
    return client.post("/workflows", headers=tenant["op"], json=payload)


def _escalate(client, tenant, visitor="wf"):
    return client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": visitor, "message": "vorrei un rimborso"}
    ).json()["conversation_id"]


def _conv(conversation_id):
    with Session(db.engine) as session:
        return session.get(db.Conversation, conversation_id)


def _row(client, tenant, conv_id):
    rows = client.get("/conversations", headers=tenant["op"]).json()
    return next(r for r in rows if r["conversation"]["id"] == conv_id)


def _other_tenant(client, name="Wf Other"):
    other = client.post("/admin/clients", headers=ADMIN, json={"name": name}).json()
    email = f"{name.lower().replace(' ', '-')}@other.it"
    client.post(
        f"/admin/clients/{other['id']}/operators", headers=ADMIN, json={"email": email, "password": "password1"}
    )
    token = client.post("/operator/login", json={"email": email, "password": "password1"}).json()["token"]
    return {"cid": other["id"], "api_key": other["api_key"], "op": {"Authorization": f"Bearer {token}"}}


# ---- configuration ----


def test_catalog_and_creation(client, tenant):
    created = _workflow(client, tenant).json()
    assert created["trigger"] == "conversation.escalated"
    assert created["actions"] == [{"type": "set_priority", "value": "urgent"}]

    listed = client.get("/workflows", headers=tenant["op"]).json()
    assert listed["catalog"]["triggers"] == list(workflows.TRIGGERS)
    assert listed["catalog"]["action_types"] == list(workflows.ACTION_TYPES)
    assert [w["id"] for w in listed["workflows"]] == [created["id"]]


def test_invalid_rules_are_refused_at_save_time(client, tenant):
    assert _workflow(client, tenant, trigger="conversation.exploded").status_code == 400
    assert _workflow(client, tenant, actions=[]).status_code == 400
    assert _workflow(client, tenant, actions=[{"type": "launch_missiles"}]).status_code == 400
    assert _workflow(client, tenant, actions=[{"type": "set_priority", "value": "altissima"}]).status_code == 400
    assert _workflow(client, tenant, conditions=[{"field": "colore", "op": "eq", "value": "blu"}]).status_code == 400
    assert _workflow(client, tenant, conditions=[{"field": "status", "op": "sniffa", "value": "open"}]).status_code == 400
    assert _workflow(client, tenant, conditions=[{"field": "rating_score", "op": "lt", "value": "molto"}]).status_code == 400
    assert _workflow(client, tenant, actions=[{"type": "send_email", "to": "non-una-email"}]).status_code == 400
    assert client.get("/workflows", headers=tenant["op"]).json()["workflows"] == []


def test_rule_cannot_reference_another_tenant(client, tenant):
    other = _other_tenant(client)
    their_department = client.post("/departments", headers=other["op"], json={"name": "Loro"}).json()
    their_operator = client.get(f"/admin/clients/{other['cid']}/operators", headers=ADMIN).json()[0]
    their_hook = client.post(
        "/webhooks", headers=other["op"], json={"url": "https://loro.example.test/h", "events": []}
    ).json()

    assert _workflow(
        client, tenant, actions=[{"type": "set_department", "department_id": their_department["id"]}]
    ).status_code == 400
    assert _workflow(
        client, tenant, actions=[{"type": "assign_operator", "operator_id": their_operator["id"]}]
    ).status_code == 400
    assert _workflow(
        client, tenant, actions=[{"type": "send_webhook", "endpoint_id": their_hook["id"]}]
    ).status_code == 400


def test_workflows_are_tenant_scoped(client, tenant):
    created = _workflow(client, tenant).json()
    other = _other_tenant(client, "Scope Other")

    assert client.get("/workflows", headers=other["op"]).json()["workflows"] == []
    assert client.patch(f"/workflows/{created['id']}", headers=other["op"], json={"active": False}).status_code == 404
    assert client.delete(f"/workflows/{created['id']}", headers=other["op"]).status_code == 404
    assert client.get(f"/workflows/{created['id']}/runs", headers=other["op"]).status_code == 404
    assert client.post(
        f"/workflows/{created['id']}/preview", headers=other["op"], json={"conversation_id": 1}
    ).status_code == 404


# ---- execution ----


def test_action_runs_on_its_trigger(client, tenant):
    _workflow(client, tenant)
    conv_id = _escalate(client, tenant)
    assert _conv(conv_id).priority == "urgent"


def test_conditions_gate_the_actions(client, tenant):
    """Stessa regola, stesso trigger: scatta solo sulla conversazione che soddisfa la condizione."""
    _workflow(
        client, tenant, trigger="conversation.closed",
        conditions=[{"field": "priority", "op": "eq", "value": "high"}],
        actions=[{"type": "add_tag", "name": "Da rivedere"}],
    )
    normale = _escalate(client, tenant, visitor="normale")
    importante = _escalate(client, tenant, visitor="importante")
    client.patch(f"/conversations/{importante}/routing", headers=tenant["op"], json={"priority": "high"})

    for conv_id in (normale, importante):
        client.post(f"/conversations/{conv_id}/status", headers=tenant["op"], json={"status": "closed"})

    assert _row(client, tenant, normale)["tags"] == []
    assert [t["name"] for t in _row(client, tenant, importante)["tags"]] == ["Da rivedere"]


def test_multiple_actions_apply_in_order(client, tenant):
    department = client.post("/departments", headers=tenant["op"], json={"name": "Resi"}).json()
    _workflow(
        client, tenant,
        actions=[
            {"type": "set_priority", "value": "high"},
            {"type": "set_department", "department_id": department["id"]},
            {"type": "add_tag", "name": "Automatico"},
        ],
    )
    conv_id = _escalate(client, tenant)

    conv = _conv(conv_id)
    assert conv.priority == "high"
    assert conv.department_id == department["id"]
    assert [t["name"] for t in _row(client, tenant, conv_id)["tags"]] == ["Automatico"]


def test_round_robin_action_uses_the_routing_pool(client, tenant):
    _workflow(client, tenant, actions=[{"type": "assign_round_robin"}])
    client.put("/routing-settings", headers=tenant["op"], json={"mode": "round_robin"})
    operator_id = client.get("/team/operators", headers=tenant["op"]).json()[0]["id"]

    conv_id = _escalate(client, tenant)
    assert _conv(conv_id).assigned_operator_id == operator_id


def test_close_action_and_loop_protection(client, tenant):
    """Chiudere emette conversation.closed: la regola che chiude su quell'evento non deve
    rientrare all'infinito."""
    _workflow(client, tenant, name="Chiudi", actions=[{"type": "close_conversation"}])
    _workflow(
        client, tenant, name="Richiudi", trigger="conversation.closed",
        actions=[{"type": "close_conversation"}],
    )
    conv_id = _escalate(client, tenant)

    assert _conv(conv_id).status == "closed"
    with Session(db.engine) as session:
        runs = session.exec(select(db.WorkflowRun).order_by(db.WorkflowRun.id)).all()
        names = {w.id: w.name for w in session.exec(select(db.Workflow)).all()}
    # una sola cascata: "Chiudi" (sull'escalation) chiude ed emette conversation.closed, e
    # "Richiudi" trova la conversazione già chiusa, quindi non riemette nulla
    applied = {names[r.workflow_id]: json.loads(r.applied) for r in runs}
    assert len(runs) == 2
    assert applied == {"Chiudi": ["conversazione chiusa"], "Richiudi": ["già chiusa"]}


def test_classification_trigger(client, tenant, monkeypatch):
    monkeypatch.setattr(
        tagging, "classify", lambda transcript: {"intent": "reclamo", "topic": "ritardo", "urgency": "alta"}
    )
    _workflow(
        client, tenant, trigger="conversation.classified",
        conditions=[{"field": "intent", "op": "eq", "value": "reclamo"}],
        actions=[{"type": "set_priority", "value": "urgent"}],
    )
    conv_id = client.post(
        "/chat", headers=tenant["key"], json={"visitor_id": "cls", "message": "il pacco non arriva"}
    ).json()["conversation_id"]

    client.post(f"/conversations/{conv_id}/classify", headers=tenant["op"])
    assert _conv(conv_id).priority == "urgent"


def test_rating_trigger_with_numeric_condition(client, tenant):
    _workflow(
        client, tenant, trigger="conversation.rated",
        conditions=[{"field": "rating_score", "op": "lt", "value": 3}],
        actions=[{"type": "add_tag", "name": "Da richiamare"}],
    )
    chat = client.post("/chat", headers=tenant["key"], json={"visitor_id": "csat", "message": "ciao"}).json()

    client.post("/chat/rating", headers=tenant["key"], json={
        "conversation_id": chat["conversation_id"], "score": 5,
        "conversation_token": chat["conversation_token"],
    })
    assert _row(client, tenant, chat["conversation_id"])["tags"] == []

    client.post("/chat/rating", headers=tenant["key"], json={
        "conversation_id": chat["conversation_id"], "score": 2,
        "conversation_token": chat["conversation_token"],
    })
    assert [t["name"] for t in _row(client, tenant, chat["conversation_id"])["tags"]] == ["Da richiamare"]


def test_webhook_action_queues_a_signed_delivery(client, tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(webhooks, "_post", lambda url, body, headers: calls.append((url, body, headers)) or 200)
    endpoint = client.post(
        "/webhooks", headers=tenant["op"], json={"url": "https://crm.example.test/h", "events": ["sla.breached"]}
    ).json()
    _workflow(client, tenant, actions=[{"type": "send_webhook", "endpoint_id": endpoint["id"]}])

    conv_id = _escalate(client, tenant)
    with Session(db.engine) as session:
        webhooks.dispatch_pending(session)

    bodies = [json.loads(body) for _, body, _ in calls]
    workflow_calls = [b for b in bodies if b.get("source") == "workflow"]
    assert len(workflow_calls) == 1
    assert workflow_calls[0]["data"]["conversation_id"] == conv_id


def test_email_action_uses_the_email_service(client, tenant, monkeypatch):
    sent = []
    # il client_id non è decorativo: senza, l'email non finisce nel costo di quel tenant
    monkeypatch.setattr(workflows.email_service, "send_email",
                        lambda to, subject, body, **kw: sent.append((to, subject, kw.get("client_id"))))
    _workflow(client, tenant, actions=[{"type": "send_email", "to": "capo@acme.it", "subject": "Escalation"}])

    _escalate(client, tenant)
    assert sent == [("capo@acme.it", "Escalation", tenant["cid"])]


def test_inactive_workflow_does_nothing(client, tenant):
    created = _workflow(client, tenant).json()
    client.patch(f"/workflows/{created['id']}", headers=tenant["op"], json={"active": False})
    conv_id = _escalate(client, tenant)
    assert _conv(conv_id).priority == "normal"
    assert client.get(f"/workflows/{created['id']}/runs", headers=tenant["op"]).json() == []


def test_failing_action_is_logged_without_breaking_the_conversation(client, tenant, monkeypatch):
    _workflow(client, tenant, actions=[{"type": "add_tag", "name": "Boom"}])
    monkeypatch.setattr(tagging, "get_or_create_tag", lambda *args, **kwargs: None)  # simula limite tag

    conv_id = _escalate(client, tenant)  # l'escalation deve comunque riuscire
    assert _conv(conv_id).status == "escalated"

    created = client.get("/workflows", headers=tenant["op"]).json()["workflows"][0]
    runs = client.get(f"/workflows/{created['id']}/runs", headers=tenant["op"]).json()
    assert runs[0]["matched"] is True
    assert runs[0]["error"]


def test_run_log_records_non_matching_evaluations(client, tenant):
    created = _workflow(
        client, tenant, conditions=[{"field": "priority", "op": "eq", "value": "urgent"}]
    ).json()
    conv_id = _escalate(client, tenant)

    runs = client.get(f"/workflows/{created['id']}/runs", headers=tenant["op"]).json()
    assert len(runs) == 1
    assert runs[0]["matched"] is False
    assert runs[0]["conversation_id"] == conv_id
    assert client.get("/workflows", headers=tenant["op"]).json()["workflows"][0]["run_count"] == 0


def test_preview_does_not_apply_anything(client, tenant):
    created = _workflow(
        client, tenant, conditions=[{"field": "status", "op": "eq", "value": "escalated"}]
    ).json()
    client.patch(f"/workflows/{created['id']}", headers=tenant["op"], json={"active": False})
    conv_id = _escalate(client, tenant)

    preview = client.post(
        f"/workflows/{created['id']}/preview", headers=tenant["op"], json={"conversation_id": conv_id}
    ).json()
    assert preview["matched"] is True
    assert preview["actions"] == [{"type": "set_priority", "value": "urgent"}]
    assert preview["context"]["status"] == "escalated"
    assert _conv(conv_id).priority == "normal"  # nessuna modifica applicata


def test_workflows_never_cross_tenants_at_runtime(client, tenant):
    other = _other_tenant(client, "Runtime Other")
    client.post("/workflows", headers=other["op"], json={
        "name": "Loro", "trigger": "conversation.escalated",
        "conditions": [], "actions": [{"type": "set_priority", "value": "urgent"}],
    })

    conv_id = _escalate(client, tenant)
    assert _conv(conv_id).priority == "normal"  # la regola dell'altro tenant non tocca la mia
    with Session(db.engine) as session:
        assert session.exec(select(db.WorkflowRun)).all() == []


def test_deleting_a_workflow_removes_its_runs(client, tenant):
    created = _workflow(client, tenant).json()
    _escalate(client, tenant)
    assert client.get(f"/workflows/{created['id']}/runs", headers=tenant["op"]).json() != []

    assert client.delete(f"/workflows/{created['id']}", headers=tenant["op"]).status_code == 200
    with Session(db.engine) as session:
        assert session.exec(select(db.WorkflowRun)).all() == []


def test_wait_persists_and_executes_remaining_actions(client, tenant):
    created = _workflow(client, tenant, actions=[
        {"type": "wait", "minutes": 60, "cancel_on_reply": True},
        {"type": "set_priority", "value": "urgent"},
    ]).json()
    conv_id = _escalate(client, tenant, visitor="delayed")
    assert _conv(conv_id).priority == "normal"

    with Session(db.engine) as session:
        queued = session.exec(select(db.WorkflowScheduledAction)).one()
        assert queued.status == "pending"
        workflows.dispatch_scheduled(session, now=queued.run_at + timedelta(seconds=1))

    assert _conv(conv_id).priority == "urgent"
    scheduled = client.get(f"/workflows/{created['id']}/scheduled", headers=tenant["op"]).json()
    assert scheduled[0]["status"] == "completed"


def test_wait_is_cancelled_when_a_human_replies(client, tenant):
    created = _workflow(client, tenant, actions=[
        {"type": "wait", "minutes": 60},
        {"type": "set_priority", "value": "urgent"},
    ]).json()
    conv_id = _escalate(client, tenant, visitor="delayed-cancel")
    with Session(db.engine) as session:
        session.add(db.Message(conversation_id=conv_id, role="operator", content="Ci penso io"))
        session.commit()
        queued = session.exec(select(db.WorkflowScheduledAction)).one()
        workflows.dispatch_scheduled(session, now=queued.run_at + timedelta(seconds=1))

    assert _conv(conv_id).priority == "normal"
    scheduled = client.get(f"/workflows/{created['id']}/scheduled", headers=tenant["op"]).json()
    assert scheduled[0]["status"] == "cancelled"
    assert scheduled[0]["error"] == "nuova risposta ricevuta"


def test_wait_validation_requires_a_following_action(client, tenant):
    assert _workflow(client, tenant, actions=[{"type": "wait", "minutes": 60}]).status_code == 400
    assert _workflow(client, tenant, actions=[
        {"type": "wait", "minutes": 0}, {"type": "close_conversation"}
    ]).status_code == 400
