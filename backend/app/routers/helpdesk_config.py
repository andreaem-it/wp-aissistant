"""Help desk configuration and connectors.

The settings behind the inbox rather than the inbox itself: departments and their queues, SLA
policies, the routing mode, the working calendar, canned replies and info fields, plus the
outbound connectors — CRM, external help desks, operator push.

Provider credentials never land here: the CRM and help desk modules keep them in their adapters
and this area stores only the mapping and the outcome of the last attempt.

Seventh area extracted from main.py. The help desk surface is 62 endpoints, too many for one
router — the inbox proper follows in its own phase. See `docs/handoff.md`.
"""
import json
import logging
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from .. import crm as crm_service
from .. import helpdesk as helpdesk_service
from .. import push as push_service
from ..conversations import (
    PRIORITIES, operator_name as _operator_name, require_conversation as _require_conversation,
)
from ..crm import CRM_PROVIDERS
from ..db import (
    CannedResponse, Contact, Conversation, CrmConnection, CrmSync, Department, DepartmentMember,
    HelpdeskConnection, HelpdeskExport, InfoField, Message, Operator, PushSubscription,
    RoutingSetting, SlaPolicy, SupportSchedule, Ticket, get_session,
)
from ..deps import audit as _audit, require_operator
from ..helpdesk import HELPDESK_PROVIDERS, export_payload as _helpdesk_export_payload
from ..routing import (
    ROUTING_MODES,
    apply_sla as _apply_sla,
    require_department as _require_department,
    routing_setting as _routing_setting,
    save_support_schedule as _save_support_schedule,
    support_schedule_payload as _support_schedule_payload,
    validated_support_schedule as _validated_support_schedule,
)
from ..util import iso as _iso, slugify as _slugify

logger = logging.getLogger("wpai")

router = APIRouter()


def _routing_payload(setting: RoutingSetting | None) -> dict:
    return {
        "mode": setting.mode if setting else "off",
        "fallback_department_id": setting.fallback_department_id if setting else None,
        "last_operator_id": setting.last_operator_id if setting else None,
    }


@router.get("/routing-settings")
def get_routing_settings(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    return _routing_payload(_routing_setting(session, operator.client_id))


@router.put("/routing-settings")
def set_routing_settings(
    mode: str = Body(...),
    fallback_department_id: int | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    if mode not in ROUTING_MODES:
        raise HTTPException(400, "invalid mode")
    if fallback_department_id is not None:
        _require_department(session, operator.client_id, fallback_department_id)
    setting = _routing_setting(session, operator.client_id)
    if setting is None:
        setting = RoutingSetting(client_id=operator.client_id)
    setting.mode = mode
    setting.fallback_department_id = fallback_department_id
    setting.updated_at = datetime.utcnow()
    session.add(setting)
    session.commit()
    session.refresh(setting)
    _audit(
        session, "operator", operator.email, "routing.update",
        target=f"client:{operator.client_id}", client_id=operator.client_id,
        detail={"mode": mode, "fallback_department_id": fallback_department_id},
    )
    return _routing_payload(setting)


@router.get("/departments")
def list_departments(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(Department).where(Department.client_id == operator.client_id).order_by(Department.name)
    ).all()
    return [{"id": row.id, "name": row.name} for row in rows]


@router.post("/departments")
def create_department(
    name: str = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean = name.strip()[:80]
    if not clean:
        raise HTTPException(400, "name required")
    existing = session.exec(
        select(Department).where(
            Department.client_id == operator.client_id,
            func.lower(Department.name) == clean.lower(),
        )
    ).first()
    if existing:
        raise HTTPException(409, "department already exists")
    department = Department(client_id=operator.client_id, name=clean)
    session.add(department)
    session.commit()
    session.refresh(department)
    _audit(session, "operator", operator.email, "department.create", target=f"department:{department.id}", client_id=operator.client_id)
    return {"id": department.id, "name": department.name}


@router.get("/departments/{department_id}/members")
def list_department_members(
    department_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Operators in the queue's round-robin pool."""
    _require_department(session, operator.client_id, department_id)
    rows = session.exec(
        select(Operator, DepartmentMember)
        .join(DepartmentMember, DepartmentMember.operator_id == Operator.id)
        .where(DepartmentMember.department_id == department_id, DepartmentMember.client_id == operator.client_id)
        .order_by(Operator.id)
    ).all()
    return [{"id": op.id, "name": _operator_name(op), "email": op.email} for op, _ in rows]


@router.post("/departments/{department_id}/members")
def add_department_member(
    department_id: int,
    operator_id: int = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_department(session, operator.client_id, department_id)
    member_operator = session.get(Operator, operator_id)
    if not member_operator or member_operator.client_id != operator.client_id:
        raise HTTPException(404, "operator not found")
    existing = session.exec(
        select(DepartmentMember).where(
            DepartmentMember.department_id == department_id,
            DepartmentMember.operator_id == operator_id,
        )
    ).first()
    if existing:
        return {"ok": True, "id": existing.id}
    row = DepartmentMember(
        client_id=operator.client_id, department_id=department_id, operator_id=operator_id
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(
        session, "operator", operator.email, "department.member_add",
        target=f"department:{department_id}", client_id=operator.client_id,
        detail={"operator_id": operator_id},
    )
    return {"ok": True, "id": row.id}


@router.delete("/departments/{department_id}/members/{operator_id}")
def remove_department_member(
    department_id: int,
    operator_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    _require_department(session, operator.client_id, department_id)
    row = session.exec(
        select(DepartmentMember).where(
            DepartmentMember.client_id == operator.client_id,
            DepartmentMember.department_id == department_id,
            DepartmentMember.operator_id == operator_id,
        )
    ).first()
    if not row:
        raise HTTPException(404, "member not found")
    session.delete(row)
    session.commit()
    _audit(
        session, "operator", operator.email, "department.member_remove",
        target=f"department:{department_id}", client_id=operator.client_id,
        detail={"operator_id": operator_id},
    )
    return {"ok": True}


@router.delete("/departments/{department_id}")
def delete_department(
    department_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    """Deleting a queue must never orphan anything hanging off it: its members, the SLA
    policies scoped to it and the routing fallback go away, and its conversations fall back to
    the generic queue (keeping their SLA clock, re-matched against the remaining policies)."""
    department = session.get(Department, department_id)
    if not department or department.client_id != operator.client_id:
        raise HTTPException(404, "department not found")
    for member in session.exec(
        select(DepartmentMember).where(DepartmentMember.department_id == department.id)
    ).all():
        session.delete(member)
    setting = _routing_setting(session, operator.client_id)
    if setting and setting.fallback_department_id == department.id:
        setting.fallback_department_id = None
        session.add(setting)
    scoped_policy_ids = [
        p.id for p in session.exec(select(SlaPolicy).where(SlaPolicy.department_id == department.id)).all()
    ]
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.department_id == department.id,
        )
    ).all():
        conv.department_id = None
        conv.sla_policy_id = None
        _apply_sla(session, conv)  # re-match against the policies that remain
        session.add(conv)
    # a policy scoped to this department can still be referenced by conversations that have
    # since moved to another queue: detach those before dropping the policies
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.sla_policy_id.in_(scoped_policy_ids),
        )
    ).all() if scoped_policy_ids else []:
        conv.sla_policy_id = None
        _apply_sla(session, conv)
        session.add(conv)
    session.flush()
    for policy_id in scoped_policy_ids:
        policy = session.get(SlaPolicy, policy_id)
        if policy is not None:
            session.delete(policy)
    session.flush()
    session.delete(department)
    session.commit()
    _audit(session, "operator", operator.email, "department.delete", target=f"department:{department_id}", client_id=operator.client_id)
    return {"ok": True}


@router.get("/support-schedule")
def get_support_schedule(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    row = session.exec(select(SupportSchedule).where(
        SupportSchedule.client_id == operator.client_id,
    )).first()
    return _support_schedule_payload(row)


@router.put("/support-schedule")
def set_support_schedule(
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = _save_support_schedule(session, operator.client_id, body, "panel")
    _audit(session, "operator", operator.email, "support_schedule.update",
           target=f"client:{operator.client_id}", client_id=operator.client_id,
           detail={"enabled": row.enabled, "timezone": row.timezone})
    return _support_schedule_payload(row)


def _clean_minutes(value: int) -> int:
    """0 disables the target; anything above a year is a configuration mistake."""
    return max(0, min(int(value), 525600))


def _sla_policy_payload(policy: SlaPolicy) -> dict:
    return {
        "id": policy.id,
        "name": policy.name,
        "department_id": policy.department_id,
        "priority": policy.priority,
        "first_response_minutes": policy.first_response_minutes,
        "resolution_minutes": policy.resolution_minutes,
        "active": policy.active,
    }


def _recompute_running_slas(session: Session, client_id: int) -> None:
    """Re-match every conversation with a running SLA after the policies changed, so the inbox
    never shows a deadline computed from a policy that no longer exists."""
    convs = session.exec(
        select(Conversation).where(
            Conversation.client_id == client_id,
            Conversation.sla_started_at.is_not(None),
            Conversation.closed_at.is_(None),
        )
    ).all()
    for conv in convs:
        _apply_sla(session, conv)
        session.add(conv)
    session.commit()


@router.get("/sla-policies")
def list_sla_policies(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(SlaPolicy).where(SlaPolicy.client_id == operator.client_id).order_by(SlaPolicy.id)
    ).all()
    return [_sla_policy_payload(row) for row in rows]


@router.post("/sla-policies")
def create_sla_policy(
    name: str = Body(...),
    first_response_minutes: int = Body(60),
    resolution_minutes: int = Body(480),
    department_id: int | None = Body(None),
    priority: str = Body(""),
    active: bool = Body(True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_name = name.strip()[:80]
    if not clean_name:
        raise HTTPException(400, "name required")
    if priority and priority not in PRIORITIES:
        raise HTTPException(400, "invalid priority")
    if department_id is not None:
        _require_department(session, operator.client_id, department_id)
    policy = SlaPolicy(
        client_id=operator.client_id,
        name=clean_name,
        department_id=department_id,
        priority=priority,
        first_response_minutes=_clean_minutes(first_response_minutes),
        resolution_minutes=_clean_minutes(resolution_minutes),
        active=active,
    )
    session.add(policy)
    session.commit()
    session.refresh(policy)
    _recompute_running_slas(session, operator.client_id)  # a new policy may be the better match
    _audit(
        session, "operator", operator.email, "sla_policy.create",
        target=f"sla_policy:{policy.id}", client_id=operator.client_id,
        detail=_sla_policy_payload(policy),
    )
    return _sla_policy_payload(policy)


@router.patch("/sla-policies/{policy_id}")
def update_sla_policy(
    policy_id: int,
    name: str | None = Body(None),
    first_response_minutes: int | None = Body(None),
    resolution_minutes: int | None = Body(None),
    priority: str | None = Body(None),
    active: bool | None = Body(None),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    policy = session.get(SlaPolicy, policy_id)
    if not policy or policy.client_id != operator.client_id:
        raise HTTPException(404, "sla policy not found")
    if name is not None:
        clean_name = name.strip()[:80]
        if not clean_name:
            raise HTTPException(400, "name required")
        policy.name = clean_name
    if priority is not None:
        if priority and priority not in PRIORITIES:
            raise HTTPException(400, "invalid priority")
        policy.priority = priority
    if first_response_minutes is not None:
        policy.first_response_minutes = _clean_minutes(first_response_minutes)
    if resolution_minutes is not None:
        policy.resolution_minutes = _clean_minutes(resolution_minutes)
    if active is not None:
        policy.active = active
    session.add(policy)
    session.commit()
    _recompute_running_slas(session, operator.client_id)
    _audit(
        session, "operator", operator.email, "sla_policy.update",
        target=f"sla_policy:{policy_id}", client_id=operator.client_id,
        detail=_sla_policy_payload(policy),
    )
    return _sla_policy_payload(policy)


@router.delete("/sla-policies/{policy_id}")
def delete_sla_policy(
    policy_id: int,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    policy = session.get(SlaPolicy, policy_id)
    if not policy or policy.client_id != operator.client_id:
        raise HTTPException(404, "sla policy not found")
    for conv in session.exec(
        select(Conversation).where(
            Conversation.client_id == operator.client_id,
            Conversation.sla_policy_id == policy_id,
        )
    ).all():
        conv.sla_policy_id = None
        session.add(conv)
    session.flush()
    session.delete(policy)
    session.commit()
    # the detached conversations now follow whichever policy still matches (possibly none)
    _recompute_running_slas(session, operator.client_id)
    _audit(
        session, "operator", operator.email, "sla_policy.delete",
        target=f"sla_policy:{policy_id}", client_id=operator.client_id,
    )
    return {"ok": True}


@router.get("/canned-responses")
def list_canned(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(CannedResponse).where(CannedResponse.client_id == operator.client_id)
        .order_by(CannedResponse.position, CannedResponse.id)
    ).all()
    return [{"id": r.id, "title": r.title, "body": r.body, "position": r.position} for r in rows]


@router.post("/canned-responses")
def create_canned(
    title: str = Body(...),
    body: str = Body(...),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = CannedResponse(client_id=operator.client_id, title=title, body=body, position=position)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "title": row.title, "body": row.body, "position": row.position}


@router.delete("/canned-responses/{canned_id}")
def delete_canned(canned_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    row = session.get(CannedResponse, canned_id)
    if not row or row.client_id != operator.client_id:
        raise HTTPException(404, "not found")
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.get("/info-fields")
def list_info_fields(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(InfoField).where(InfoField.client_id == operator.client_id)
        .order_by(InfoField.position, InfoField.id)
    ).all()
    return [{"id": r.id, "label": r.label, "key": r.key, "position": r.position} for r in rows]


@router.post("/info-fields")
def create_info_field(
    label: str = Body(...),
    key: str | None = Body(None),
    position: int = Body(0),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    slug = _slugify(key or label)
    # ensure the key is unique within the client so placeholder substitution is unambiguous
    existing = {f.key for f in session.exec(select(InfoField).where(InfoField.client_id == operator.client_id)).all()}
    base, n = slug, 2
    while slug in existing:
        slug = f"{base}_{n}"
        n += 1
    row = InfoField(client_id=operator.client_id, label=label, key=slug, position=position)
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"id": row.id, "label": row.label, "key": row.key, "position": row.position}


@router.delete("/info-fields/{field_id}")
def delete_info_field(field_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    row = session.get(InfoField, field_id)
    if not row or row.client_id != operator.client_id:
        raise HTTPException(404, "not found")
    session.delete(row)
    session.commit()
    return {"ok": True}


@router.get("/conversations/{conversation_id}/info")
def get_conversation_info(conversation_id: int, operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    """Operator-only: the structured info values saved on this conversation (keyed by
    InfoField.key). Kept separate from /messages so it never leaks to the visitor's widget."""
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    return {"info": json.loads(conv.info) if conv.info else {}}


@router.put("/conversations/{conversation_id}/info")
def set_conversation_info(
    conversation_id: int,
    info: dict = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    conv = session.get(Conversation, conversation_id)
    if not conv or conv.client_id != operator.client_id:
        raise HTTPException(404, "conversation not found")
    # store only string values, capped, to keep the JSON blob bounded
    clean = {str(k): str(v)[:2000] for k, v in info.items()}
    conv.info = json.dumps(clean)
    conv.updated_at = datetime.utcnow()
    session.add(conv)
    session.commit()
    return {"ok": True, "info": clean}


def _crm_connection_payload(row: CrmConnection) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "external_account_id": row.external_account_id,
        "enabled": row.enabled,
        "updated_at": _iso(row.updated_at),
    }


@router.get("/crm/connections")
def list_crm_connections(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    rows = session.exec(
        select(CrmConnection).where(CrmConnection.client_id == operator.client_id)
        .order_by(CrmConnection.provider)
    ).all()
    return {"providers": list(CRM_PROVIDERS), "connections": [_crm_connection_payload(row) for row in rows]}


@router.put("/crm/connections/{provider}")
def set_crm_connection(
    provider: str,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = provider.strip().lower()
    if provider not in CRM_PROVIDERS:
        raise HTTPException(400, "Provider CRM non supportato")
    account_id = str(body.get("external_account_id", "")).strip()
    if not account_id or len(account_id) > 255 or not re.fullmatch(r"[A-Za-z0-9_.:@/-]+", account_id):
        raise HTTPException(400, "Identificativo account non valido")
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id, CrmConnection.provider == provider,
    )).first()
    if row is None:
        row = CrmConnection(client_id=operator.client_id, provider=provider)
    row.external_account_id = account_id
    row.enabled = bool(body.get("enabled", True))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "crm.connection.update",
           target=f"crm:{provider}", client_id=operator.client_id,
           detail={"enabled": row.enabled})
    return _crm_connection_payload(row)


@router.post("/crm/connect/brevo")
def connect_brevo(
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    api_key = str(body.get("api_key", "")).strip()
    if len(api_key) < 20 or len(api_key) > 512:
        raise HTTPException(400, "Chiave Brevo non valida")
    connected, account_id, error = crm_service.configure_brevo(client_id=operator.client_id, api_key=api_key)
    if not connected:
        raise HTTPException(422, error or "Collegamento Brevo non riuscito")
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id, CrmConnection.provider == "brevo",
    )).first() or CrmConnection(client_id=operator.client_id, provider="brevo")
    row.external_account_id = account_id
    row.enabled = True
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "crm.connection.update", target="crm:brevo",
           client_id=operator.client_id, detail={"enabled": True})
    return _crm_connection_payload(row)


@router.delete("/crm/connections/{provider}")
def delete_crm_connection(
    provider: str,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(select(CrmConnection).where(
        CrmConnection.client_id == operator.client_id,
        CrmConnection.provider == provider.strip().lower(),
    )).first()
    if row is None:
        raise HTTPException(404, "Connessione CRM non trovata")
    if not crm_service.disconnect(client_id=operator.client_id, provider=row.provider):
        raise HTTPException(503, "Impossibile revocare in sicurezza la credenziale CRM")
    for sync in session.exec(select(CrmSync).where(CrmSync.connection_id == row.id)).all():
        session.delete(sync)
    session.delete(row)
    session.commit()
    _audit(session, "operator", operator.email, "crm.connection.delete",
           target=f"crm:{provider}", client_id=operator.client_id)
    return {"ok": True}


def _helpdesk_connection_payload(row: HelpdeskConnection) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "external_account_id": row.external_account_id,
        "enabled": row.enabled,
        "updated_at": _iso(row.updated_at),
    }


@router.get("/helpdesk/connections")
def list_helpdesk_connections(
    operator: Operator = Depends(require_operator), session: Session = Depends(get_session),
):
    rows = session.exec(
        select(HelpdeskConnection).where(HelpdeskConnection.client_id == operator.client_id)
        .order_by(HelpdeskConnection.provider)
    ).all()
    return {"providers": list(HELPDESK_PROVIDERS), "connections": [_helpdesk_connection_payload(row) for row in rows]}


@router.put("/helpdesk/connections/{provider}")
def set_helpdesk_connection(
    provider: str,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = provider.strip().lower()
    if provider not in HELPDESK_PROVIDERS:
        raise HTTPException(400, "Provider helpdesk non supportato")
    account_id = str(body.get("external_account_id", "")).strip()
    if not account_id or len(account_id) > 255 or not re.fullmatch(r"[A-Za-z0-9_.:@/-]+", account_id):
        raise HTTPException(400, "Identificativo account non valido")
    row = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider,
    )).first() or HelpdeskConnection(client_id=operator.client_id, provider=provider)
    row.external_account_id = account_id
    row.enabled = bool(body.get("enabled", True))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    _audit(session, "operator", operator.email, "helpdesk.connection.update",
           target=f"helpdesk:{provider}", client_id=operator.client_id,
           detail={"enabled": row.enabled})
    return _helpdesk_connection_payload(row)


@router.delete("/helpdesk/connections/{provider}")
def delete_helpdesk_connection(
    provider: str,
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider.strip().lower(),
    )).first()
    if row is None:
        raise HTTPException(404, "Connessione helpdesk non trovata")
    for export in session.exec(select(HelpdeskExport).where(HelpdeskExport.connection_id == row.id)).all():
        session.delete(export)
    session.delete(row)
    session.commit()
    _audit(session, "operator", operator.email, "helpdesk.connection.delete",
           target=f"helpdesk:{provider}", client_id=operator.client_id)
    return {"ok": True}


@router.post("/tickets/{ticket_id}/helpdesk-export")
def export_ticket_to_helpdesk(
    ticket_id: int,
    body: dict = Body(...),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    provider = str(body.get("provider", "")).strip().lower()
    ticket = session.get(Ticket, ticket_id)
    conversation = session.get(Conversation, ticket.conversation_id) if ticket else None
    if not ticket or not conversation or conversation.client_id != operator.client_id:
        raise HTTPException(404, "Ticket non trovato")
    connection = session.exec(select(HelpdeskConnection).where(
        HelpdeskConnection.client_id == operator.client_id,
        HelpdeskConnection.provider == provider,
        HelpdeskConnection.enabled == True,  # noqa: E712
    )).first()
    if connection is None:
        raise HTTPException(400, "Connessione helpdesk non attiva")
    export = session.exec(select(HelpdeskExport).where(
        HelpdeskExport.connection_id == connection.id,
        HelpdeskExport.ticket_id == ticket.id,
    )).first() or HelpdeskExport(
        client_id=operator.client_id, connection_id=connection.id, ticket_id=ticket.id,
    )
    export.status, export.external_id, export.external_url, export.error = "pending", "", "", ""
    export.updated_at = datetime.utcnow()
    session.add(export)
    session.commit()
    messages = session.exec(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    ).all()
    contact = session.get(Contact, conversation.contact_id) if conversation.contact_id else None
    delivered, external_id, external_url, error = helpdesk_service.export_ticket(
        client_id=operator.client_id,
        provider=provider,
        external_account_id=connection.external_account_id,
        ticket={
            "id": ticket.id,
            "reason": ticket.reason,
            "status": ticket.status,
            "created_at": _iso(ticket.created_at),
            "conversation": {
                "id": conversation.id,
                "channel": conversation.channel,
                "subject": conversation.channel_subject,
                "priority": conversation.priority,
                "visitor_url": conversation.visitor_url or "",
            },
            "contact": {
                "name": contact.name if contact else "",
                "email": (contact.email if contact else None) or conversation.visitor_email or "",
                "external_id": contact.external_id if contact else "",
            },
            "messages": [
                {"role": message.role, "content": message.content, "created_at": _iso(message.created_at)}
                for message in messages
            ],
        },
    )
    export.status = "delivered" if delivered else "failed"
    export.external_id = external_id
    export.external_url = external_url
    export.error = error[:255]
    export.updated_at = datetime.utcnow()
    session.add(export)
    session.commit()
    _audit(session, "operator", operator.email, "ticket.helpdesk_export",
           target=f"ticket:{ticket.id}", client_id=operator.client_id,
           detail={"provider": provider, "status": export.status})
    return _helpdesk_export_payload(export)


@router.get("/push/config")
def push_config(operator: Operator = Depends(require_operator), session: Session = Depends(get_session)):
    rows = session.exec(
        select(PushSubscription).where(PushSubscription.operator_id == operator.id)
    ).all()
    first = rows[0] if rows else None
    return {
        "configured": push_service.configured(),
        "public_key": push_service.VAPID_PUBLIC_KEY if push_service.configured() else "",
        "subscriptions": len(rows),
        "preferences": {
            "escalations": first.escalations if first else True,
            "assignments": first.assignments if first else True,
            "mentions": first.mentions if first else True,
            "sla_breaches": first.sla_breaches if first else True,
        },
    }


@router.post("/push/subscriptions")
def save_push_subscription(
    endpoint: str = Body(...),
    keys: dict = Body(...),
    preferences: dict = Body(default={}),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    clean_endpoint = (endpoint or "").strip()[:2000]
    p256dh = str(keys.get("p256dh", "")).strip()[:500]
    auth = str(keys.get("auth", "")).strip()[:500]
    if not clean_endpoint.startswith("https://") or not p256dh or not auth:
        raise HTTPException(400, "invalid push subscription")
    row = session.exec(select(PushSubscription).where(PushSubscription.endpoint == clean_endpoint)).first()
    if row is not None and (row.client_id != operator.client_id or row.operator_id != operator.id):
        raise HTTPException(409, "push subscription already belongs to another operator")
    if row is None:
        row = PushSubscription(
            client_id=operator.client_id, operator_id=operator.id,
            endpoint=clean_endpoint, p256dh=p256dh, auth=auth,
        )
    row.client_id = operator.client_id
    row.operator_id = operator.id
    row.p256dh = p256dh
    row.auth = auth
    for field in ("escalations", "assignments", "mentions", "sla_breaches"):
        if field in preferences:
            setattr(row, field, bool(preferences[field]))
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    return {"ok": True}


@router.patch("/push/preferences")
def update_push_preferences(
    preferences: dict = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(PushSubscription).where(PushSubscription.operator_id == operator.id)).all()
    for row in rows:
        for field in ("escalations", "assignments", "mentions", "sla_breaches"):
            if field in preferences:
                setattr(row, field, bool(preferences[field]))
        row.updated_at = datetime.utcnow()
        session.add(row)
    session.commit()
    return {"ok": True}


@router.delete("/push/subscriptions")
def delete_push_subscription(
    endpoint: str = Body(..., embed=True),
    operator: Operator = Depends(require_operator),
    session: Session = Depends(get_session),
):
    row = session.exec(
        select(PushSubscription).where(
            PushSubscription.operator_id == operator.id,
            PushSubscription.endpoint == (endpoint or "").strip(),
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()
    return {"ok": True}
