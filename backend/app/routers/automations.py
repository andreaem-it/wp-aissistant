"""Automations: no-code workflows, proactive messages and lead capture.

Three ways a tenant makes the assistant act on its own — rules on conversation events, messages
offered before the visitor asks, and forms that turn a chat into a contact.

Fifth-and-sixth area extracted from main.py — see `docs/handoff.md` for the pattern.
"""
import csv
import io
import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from sqlmodel import Session, select

from .. import crm as crm_service
from .. import workflows
from ..conversations import require_conversation as _require_conversation
from ..db import (
    CrmConnection, CrmSync, Lead, LeadForm, Operator, ProactiveExperiment, ProactiveRule,
    Workflow, WorkflowRun, WorkflowScheduledAction, get_session,
)
from ..deps import audit as _audit, require_operator
from ..leads import (
    LEAD_FIELD_TYPES, LEAD_TRIGGERS, MAX_LEAD_FIELDS, MAX_LEAD_VALUE_CHARS,
    form_payload as _lead_form_payload,
)
from ..proactive import (
    MAX_PROACTIVE_MESSAGE_CHARS, PROACTIVE_FREQUENCIES, PROACTIVE_TRIGGERS,
    ab_result as _proactive_ab_result, rule_payload as _proactive_payload,
)
from ..util import bounded_limit as _bounded_limit, iso as _iso, slugify as _slugify

logger = logging.getLogger("wpai")

router = APIRouter()


def _workflow_payload(workflow: Workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "trigger": workflow.trigger,
        "conditions": json.loads(workflow.conditions or "[]"),
        "actions": json.loads(workflow.actions or "[]"),
        "active": workflow.active,
        "position": workflow.position,
        "run_count": workflow.run_count,
        "last_run_at": _iso(workflow.last_run_at),
    }


@router.get("/workflows")
def list_workflows(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Rules plus the vocabulary the panel needs to build the editor, so triggers, fields,
    operators and actions are never duplicated (and never drift) in the frontend."""
    rows = session.exec(
        select(Workflow).where(Workflow.client_id == operator.client_id)
        .order_by(Workflow.position, Workflow.id)
    ).all()
    return {
        "catalog": {
            "triggers": list(workflows.TRIGGERS),
            "condition_fields": list(workflows.CONDITION_FIELDS),
            "condition_ops": list(workflows.CONDITION_OPS),
            "action_types": list(workflows.ACTION_TYPES),
        },
        "workflows": [_workflow_payload(row) for row in rows],
    }


@router.post("/workflows")
def create_workflow(
    name: str = Body(...),
    trigger: str = Body(...),
    conditions: list = Body([]),
    actions: list = Body([]),
    active: bool = Body(True),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if trigger not in workflows.TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    try:
        clean_conditions = workflows.validate_conditions(conditions)
        clean_actions = workflows.validate_actions(session, operator.client_id, actions)
    except workflows.WorkflowConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    workflow = Workflow(
        client_id=operator.client_id,
        name=clean_name,
        trigger=trigger,
        conditions=json.dumps(clean_conditions),
        actions=json.dumps(clean_actions),
        active=active,
        position=position,
    )
    session.add(workflow)
    session.commit()
    session.refresh(workflow)
    _audit(
        session, "operator", operator.email, "workflow.create",
        target=f"workflow:{workflow.id}", client_id=operator.client_id,
        detail={"trigger": trigger, "actions": [a["type"] for a in clean_actions]},
    )
    return _workflow_payload(workflow)


@router.patch("/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int,
    name: str | None = Body(None),
    trigger: str | None = Body(None),
    conditions: list | None = Body(None),
    actions: list | None = Body(None),
    active: bool | None = Body(None),
    position: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    if name is not None:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise HTTPException(400, "name required")
        workflow.name = clean_name
    if trigger is not None:
        if trigger not in workflows.TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        workflow.trigger = trigger
    try:
        if conditions is not None:
            workflow.conditions = json.dumps(workflows.validate_conditions(conditions))
        if actions is not None:
            workflow.actions = json.dumps(workflows.validate_actions(session, operator.client_id, actions))
    except workflows.WorkflowConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    if active is not None:
        workflow.active = active
    if position is not None:
        workflow.position = position
    workflow.updated_at = datetime.utcnow()
    session.add(workflow)
    session.commit()
    _audit(
        session, "operator", operator.email, "workflow.update",
        target=f"workflow:{workflow_id}", client_id=operator.client_id,
    )
    return _workflow_payload(workflow)


@router.delete("/workflows/{workflow_id}")
def delete_workflow(
    workflow_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    for scheduled in session.exec(select(WorkflowScheduledAction).where(WorkflowScheduledAction.workflow_id == workflow.id)).all():
        session.delete(scheduled)
    for run in session.exec(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow.id)).all():
        session.delete(run)
    session.flush()
    session.delete(workflow)
    session.commit()
    _audit(
        session, "operator", operator.email, "workflow.delete",
        target=f"workflow:{workflow_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@router.post("/workflows/{workflow_id}/preview")
def preview_workflow(
    workflow_id: int,
    conversation_id: int = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Dry run against a real conversation: says whether the rule would match and what it would
    do, without applying anything."""
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    conv = _require_conversation(session, operator.client_id, conversation_id)
    return workflows.preview(session, workflow, conv)


@router.get("/workflows/{workflow_id}/runs")
def list_workflow_runs(
    workflow_id: int,
    limit: int = 50,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    rows = session.exec(
        select(WorkflowRun)
        .where(WorkflowRun.workflow_id == workflow.id)
        .order_by(WorkflowRun.id.desc())
        .limit(_bounded_limit(limit, default=50))
    ).all()
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "event": row.event,
            "matched": row.matched,
            "applied": json.loads(row.applied or "[]"),
            "error": row.error,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


@router.get("/workflows/{workflow_id}/scheduled")
def list_workflow_scheduled(
    workflow_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    workflow = session.get(Workflow, workflow_id)
    if not workflow or workflow.client_id != operator.client_id:
        raise HTTPException(404, "workflow not found")
    rows = session.exec(
        select(WorkflowScheduledAction).where(WorkflowScheduledAction.workflow_id == workflow.id)
        .order_by(WorkflowScheduledAction.id.desc()).limit(100)
    ).all()
    return [{
        "id": row.id, "conversation_id": row.conversation_id, "status": row.status,
        "run_at": _iso(row.run_at), "attempts": row.attempts, "error": row.last_error,
        "created_at": _iso(row.created_at),
    } for row in rows]


def _proactive_experiment_payload(row: ProactiveExperiment) -> dict:
    return {
        "id": row.id, "rule_id": row.rule_id, "rule_name": row.rule_name,
        "message_a": row.message_a, "message_b": row.message_b,
        "impressions_a": row.impressions_a, "engagements_a": row.engagements_a,
        "impressions_b": row.impressions_b, "engagements_b": row.engagements_b,
        "statistical_winner": row.statistical_winner or None,
        "selected_variant": row.selected_variant or None,
        "outcome": row.outcome, "operator_email": row.operator_email,
        "created_at": _iso(row.created_at),
    }


@router.get("/proactive-rules")
def list_proactive_rules(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(ProactiveRule).where(ProactiveRule.client_id == operator.client_id)
        .order_by(ProactiveRule.position, ProactiveRule.id)
    ).all()
    history = session.exec(
        select(ProactiveExperiment).where(ProactiveExperiment.client_id == operator.client_id)
        .order_by(ProactiveExperiment.id.desc()).limit(20)
    ).all()
    return {
        "triggers": list(PROACTIVE_TRIGGERS),
        "frequencies": list(PROACTIVE_FREQUENCIES),
        "rules": [_proactive_payload(row) for row in rows],
        "experiments": [_proactive_experiment_payload(row) for row in history],
    }


@router.post("/proactive-rules")
def create_proactive_rule(
    name: str = Body(...),
    message: str = Body(...),
    message_b: str = Body(""),
    trigger_type: str = Body("time_on_page"),
    url_pattern: str = Body(""),
    delay_seconds: int = Body(15),
    frequency: str = Body("once_per_day"),
    active: bool = Body(True),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    clean_message = message.strip()[:MAX_PROACTIVE_MESSAGE_CHARS]
    if not clean_name or not clean_message:
        raise HTTPException(400, "nome e messaggio sono obbligatori")
    if trigger_type not in PROACTIVE_TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    if frequency not in PROACTIVE_FREQUENCIES:
        raise HTTPException(400, "frequenza non valida")
    rule = ProactiveRule(
        client_id=operator.client_id,
        name=clean_name,
        message=clean_message,
        message_b=message_b.strip()[:MAX_PROACTIVE_MESSAGE_CHARS],
        trigger_type=trigger_type,
        url_pattern=url_pattern.strip()[:300],
        delay_seconds=min(max(int(delay_seconds), 0), 3600),
        frequency=frequency,
        active=active,
        position=position,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    _audit(
        session, "operator", operator.email, "proactive.create",
        target=f"proactive:{rule.id}", client_id=operator.client_id,
        detail={"trigger": trigger_type},
    )
    return _proactive_payload(rule)


@router.patch("/proactive-rules/{rule_id}")
def update_proactive_rule(
    rule_id: int,
    name: str | None = Body(None),
    message: str | None = Body(None),
    message_b: str | None = Body(None),
    trigger_type: str | None = Body(None),
    url_pattern: str | None = Body(None),
    delay_seconds: int | None = Body(None),
    frequency: str | None = Body(None),
    active: bool | None = Body(None),
    position: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != operator.client_id:
        raise HTTPException(404, "rule not found")
    if name is not None:
        clean = name.strip()[:80]
        if not clean:
            raise HTTPException(400, "name required")
        rule.name = clean
    if message is not None:
        clean = message.strip()[:MAX_PROACTIVE_MESSAGE_CHARS]
        if not clean:
            raise HTTPException(400, "message required")
        rule.message = clean
    if message_b is not None:
        rule.message_b = message_b.strip()[:MAX_PROACTIVE_MESSAGE_CHARS]
    if trigger_type is not None:
        if trigger_type not in PROACTIVE_TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        rule.trigger_type = trigger_type
    if url_pattern is not None:
        rule.url_pattern = url_pattern.strip()[:300]
    if delay_seconds is not None:
        rule.delay_seconds = min(max(int(delay_seconds), 0), 3600)
    if frequency is not None:
        if frequency not in PROACTIVE_FREQUENCIES:
            raise HTTPException(400, "frequenza non valida")
        rule.frequency = frequency
    if active is not None:
        rule.active = active
    if position is not None:
        rule.position = position
    rule.updated_at = datetime.utcnow()
    session.add(rule)
    session.commit()
    _audit(
        session, "operator", operator.email, "proactive.update",
        target=f"proactive:{rule_id}", client_id=operator.client_id,
    )
    return _proactive_payload(rule)


@router.delete("/proactive-rules/{rule_id}")
def delete_proactive_rule(
    rule_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != operator.client_id:
        raise HTTPException(404, "rule not found")
    session.delete(rule)
    session.commit()
    _audit(
        session, "operator", operator.email, "proactive.delete",
        target=f"proactive:{rule_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@router.post("/proactive-rules/{rule_id}/experiment")
def finish_proactive_experiment(
    rule_id: int,
    action: str = Body(..., embed=True),  # promote | stop
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rule = session.get(ProactiveRule, rule_id)
    if not rule or rule.client_id != operator.client_id:
        raise HTTPException(404, "rule not found")
    if action not in ("promote", "stop"):
        raise HTTPException(400, "action must be 'promote' or 'stop'")
    if not rule.message_b:
        raise HTTPException(400, "no active experiment")
    result = _proactive_ab_result(rule)
    if action == "promote" and result["status"] != "winner":
        raise HTTPException(409, "the experiment has no statistically significant winner")
    selected = result["winner"] if action == "promote" else ""
    session.add(ProactiveExperiment(
        client_id=operator.client_id, rule_id=rule.id, rule_name=rule.name,
        message_a=rule.message, message_b=rule.message_b,
        impressions_a=rule.impressions, engagements_a=rule.engagements,
        impressions_b=rule.impressions_b, engagements_b=rule.engagements_b,
        statistical_winner=result.get("winner") or "", selected_variant=selected,
        outcome="promoted" if action == "promote" else "stopped",
        operator_email=operator.email,
    ))
    if selected == "b":
        rule.message = rule.message_b
    rule.message_b = ""
    rule.impressions = rule.engagements = rule.impressions_b = rule.engagements_b = 0
    rule.updated_at = datetime.utcnow()
    session.add(rule)
    session.commit()
    _audit(
        session, "operator", operator.email, f"proactive.experiment_{action}",
        target=f"proactive:{rule.id}", client_id=operator.client_id,
        detail={"selected_variant": selected or None},
    )
    return {"ok": True, "rule": _proactive_payload(rule)}


def _clean_lead_fields(raw) -> list[dict]:
    """A field is {key,label,type,required,points}. Points make the score explainable: it is
    the sum of the points of the fields the visitor actually filled, nothing hidden."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "serve almeno un campo")
    if len(raw) > MAX_LEAD_FIELDS:
        raise HTTPException(400, f"massimo {MAX_LEAD_FIELDS} campi")
    clean, seen = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(400, "ogni campo deve essere un oggetto")
        label = str(item.get("label", "")).strip()[:80]
        if not label:
            raise HTTPException(400, "ogni campo deve avere un'etichetta")
        key = _slugify(item.get("key") or label)
        if key in seen:
            raise HTTPException(400, f"chiave duplicata: {key}")
        seen.add(key)
        field_type = item.get("type", "text")
        if field_type not in LEAD_FIELD_TYPES:
            raise HTTPException(400, f"tipo campo non valido: {field_type}")
        options = [str(o).strip()[:60] for o in (item.get("options") or []) if str(o).strip()][:10]
        if field_type == "select" and not options:
            raise HTTPException(400, "un campo a scelta richiede almeno un'opzione")
        clean.append({
            "key": key,
            "label": label,
            "type": field_type,
            "required": bool(item.get("required")),
            "points": min(max(int(item.get("points") or 0), 0), 50),
            "options": options,
        })
    return clean


@router.get("/lead-forms")
def list_lead_forms(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(LeadForm).where(LeadForm.client_id == operator.client_id).order_by(LeadForm.id)
    ).all()
    return {
        "triggers": list(LEAD_TRIGGERS),
        "field_types": list(LEAD_FIELD_TYPES),
        "forms": [_lead_form_payload(row) for row in rows],
    }


@router.post("/lead-forms")
def create_lead_form(
    name: str = Body(...),
    fields: list = Body(...),
    trigger: str = Body("escalation"),
    intro: str = Body(""),
    consent_text: str = Body(""),
    active: bool = Body(True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if trigger not in LEAD_TRIGGERS:
        raise HTTPException(400, "trigger non valido")
    form = LeadForm(
        client_id=operator.client_id,
        name=clean_name,
        trigger=trigger,
        fields=json.dumps(_clean_lead_fields(fields)),
        intro=intro.strip()[:300],
        consent_text=consent_text.strip()[:500],
        active=active,
    )
    session.add(form)
    session.commit()
    session.refresh(form)
    _audit(
        session, "operator", operator.email, "lead_form.create",
        target=f"lead_form:{form.id}", client_id=operator.client_id,
    )
    return _lead_form_payload(form)


@router.patch("/lead-forms/{form_id}")
def update_lead_form(
    form_id: int,
    name: str | None = Body(None),
    fields: list | None = Body(None),
    trigger: str | None = Body(None),
    intro: str | None = Body(None),
    consent_text: str | None = Body(None),
    active: bool | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    form = session.get(LeadForm, form_id)
    if not form or form.client_id != operator.client_id:
        raise HTTPException(404, "form not found")
    if name is not None:
        clean = name.strip()[:80]
        if not clean:
            raise HTTPException(400, "name required")
        form.name = clean
    if trigger is not None:
        if trigger not in LEAD_TRIGGERS:
            raise HTTPException(400, "trigger non valido")
        form.trigger = trigger
    if fields is not None:
        form.fields = json.dumps(_clean_lead_fields(fields))
    if intro is not None:
        form.intro = intro.strip()[:300]
    if consent_text is not None:
        form.consent_text = consent_text.strip()[:500]
    if active is not None:
        form.active = active
    form.updated_at = datetime.utcnow()
    session.add(form)
    session.commit()
    _audit(
        session, "operator", operator.email, "lead_form.update",
        target=f"lead_form:{form_id}", client_id=operator.client_id,
    )
    return _lead_form_payload(form)


@router.delete("/lead-forms/{form_id}")
def delete_lead_form(
    form_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """The captured leads survive the form: they are the tenant's data, not the form's."""
    form = session.get(LeadForm, form_id)
    if not form or form.client_id != operator.client_id:
        raise HTTPException(404, "form not found")
    for lead in session.exec(select(Lead).where(Lead.form_id == form.id)).all():
        lead.form_id = None
        session.add(lead)
    session.flush()
    session.delete(form)
    session.commit()
    _audit(
        session, "operator", operator.email, "lead_form.delete",
        target=f"lead_form:{form_id}", client_id=operator.client_id,
    )
    return {"ok": True}


def _lead_query(client_id: int, min_score: int | None, days: int | None):
    query = select(Lead).where(Lead.client_id == client_id)
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
    if days:
        query = query.where(Lead.created_at >= datetime.utcnow() - timedelta(days=days))
    return query


def _csv_cell(value) -> str:
    """Quote for CSV and neutralise formula injection: a cell starting with = + - @ is executed
    by spreadsheet apps when the export is opened, so prefix it with a quote."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@router.get("/leads")
def list_leads(
    min_score: int | None = None,
    days: int | None = None,
    limit: int = 100,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rows = session.exec(
        _lead_query(operator.client_id, min_score, days)
        .order_by(Lead.id.desc())
        .limit(_bounded_limit(limit))
    ).all()
    syncs = session.exec(select(CrmSync).where(
        CrmSync.client_id == operator.client_id,
        CrmSync.lead_id.in_([row.id for row in rows]),
    )).all() if rows else []
    connections = {row.id: row.provider for row in session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
    )).all()}
    sync_by_lead: dict[int, dict] = {}
    for sync in syncs:
        sync_by_lead.setdefault(sync.lead_id, {})[connections.get(sync.connection_id, "crm")] = {
            "status": sync.status, "external_id": sync.external_id, "error": sync.error,
        }
    return [
        {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "form_id": row.form_id,
            "score": row.score,
            "consent": row.consent,
            "consent_text": row.consent_text,
            "data": json.loads(row.data or "{}"),
            "created_at": _iso(row.created_at),
            "crm_syncs": sync_by_lead.get(row.id, {}),
        }
        for row in rows
    ]


@router.get("/leads/export")
def export_leads(
    min_score: int | None = None,
    days: int | None = None,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """CSV of the captured leads, one column per field key seen in the period."""
    rows = session.exec(_lead_query(operator.client_id, min_score, days).order_by(Lead.id)).all()
    parsed = [(row, json.loads(row.data or "{}")) for row in rows]
    keys: list[str] = []
    for _, data in parsed:
        for key in data:
            if key not in keys:
                keys.append(key)
    header = ["id", "created_at", "conversation_id", "score", "consent", *keys]
    lines = [",".join(_csv_cell(h) for h in header)]
    for row, data in parsed:
        lines.append(",".join(_csv_cell(v) for v in [
            row.id, _iso(row.created_at), row.conversation_id or "", row.score,
            "sì" if row.consent else "no", *[data.get(key, "") for key in keys],
        ]))
    _audit(
        session, "operator", operator.email, "lead.export",
        client_id=operator.client_id, detail={"leads": len(parsed)},
    )
    return Response(
        content="﻿" + "\n".join(lines),  # BOM: Excel apre l'UTF-8 correttamente
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lead.csv"'},
    )


@router.post("/leads/{lead_id}/crm-sync")
def sync_lead_to_crm(
    lead_id: int,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = str(body.get("provider", "")).strip().lower()
    lead = session.exec(select(Lead).where(
        Lead.id == lead_id, Lead.client_id == operator.client_id,
    )).first()
    if lead is None:
        raise HTTPException(404, "Lead non trovato")
    connection = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
        CrmConnection.provider == provider,
        CrmConnection.enabled == True,  # noqa: E712
    )).first()
    if connection is None:
        raise HTTPException(400, "Connessione CRM non attiva")
    sync = session.exec(select(CrmSync).where(
        CrmSync.connection_id == connection.id, CrmSync.lead_id == lead.id,
    )).first()
    if sync is None:
        sync = CrmSync(client_id=operator.client_id, connection_id=connection.id, lead_id=lead.id)
    sync.status, sync.error, sync.external_id = "pending", "", ""
    sync.updated_at = datetime.utcnow()
    session.add(sync)
    session.commit()
    delivered, external_id, error = crm_service.sync_lead(
        client_id=operator.client_id,
        provider=provider,
        external_account_id=connection.external_account_id,
        lead={
            "id": lead.id,
            "conversation_id": lead.conversation_id,
            "data": json.loads(lead.data or "{}"),
            "score": lead.score,
            "consent": lead.consent,
            "consent_text": lead.consent_text,
            "created_at": _iso(lead.created_at),
        },
    )
    sync.status = "delivered" if delivered else "failed"
    sync.external_id = external_id
    sync.error = error[:255]
    sync.updated_at = datetime.utcnow()
    session.add(sync)
    session.commit()
    _audit(session, "operator", operator.email, "lead.crm_sync",
           target=f"lead:{lead.id}", client_id=operator.client_id,
           detail={"provider": provider, "delivered": delivered})
    return {"ok": delivered, "status": sync.status, "external_id": external_id, "error": error}
