"""Assignment and SLA: who a conversation goes to, and by when.

The rules that turn an escalation into someone's job — the tenant's routing mode, the queue of
operators, and the deadlines from the most specific matching policy. Shared by the inbox, the
channels and the automations, so it lives outside any one of them.
"""
import json
import logging
import os
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from . import business_hours
from .util import iso as _iso
from .db import (
    Conversation, Department, DepartmentMember, Operator, RoutingSetting, SlaPolicy,
    SupportSchedule,
)
from .logging_config import log

logger = logging.getLogger("wpai")

# how far into a deadline counts as "in scadenza": a warning with no runway left is not a warning
SLA_WARN_RATIO = float(os.getenv("SLA_WARN_RATIO", "0.75"))


def routing_setting(session: Session, client_id: int) -> RoutingSetting | None:
    return session.exec(select(RoutingSetting).where(RoutingSetting.client_id == client_id)).first()


def assignable_operators(session: Session, client_id: int, department_id: int | None) -> list[Operator]:
    """The round-robin pool: the members of the conversation's department, or every verified
    operator of the tenant when the conversation has no department. A department with no
    members has no pool — the conversation stays in that queue, unassigned, on purpose."""
    if department_id is not None:
        member_ids = [
            m.operator_id
            for m in session.exec(
                select(DepartmentMember).where(
                    DepartmentMember.client_id == client_id,
                    DepartmentMember.department_id == department_id,
                )
            ).all()
        ]
        if not member_ids:
            return []
        return session.exec(
            select(Operator)
            .where(
                Operator.client_id == client_id,
                Operator.email_verified.is_(True),
                Operator.id.in_(member_ids),
            )
            .order_by(Operator.id)
        ).all()
    return session.exec(
        select(Operator)
        .where(Operator.client_id == client_id, Operator.email_verified.is_(True))
        .order_by(Operator.id)
    ).all()


def auto_assign(session: Session, conv: Conversation) -> Operator | None:
    """Round-robin the conversation to the next operator of its queue when the tenant enabled
    it. Falls back to the configured department, then to the unassigned queue: never fails the
    escalation it is attached to. Nothing is committed here."""
    setting = routing_setting(session, conv.client_id)
    if setting is None or setting.mode != "round_robin":
        return None
    if conv.department_id is None and setting.fallback_department_id:
        department = session.get(Department, setting.fallback_department_id)
        if department and department.client_id == conv.client_id:
            conv.department_id = department.id
    if conv.assigned_operator_id is not None:
        return None
    pool = assignable_operators(session, conv.client_id, conv.department_id)
    if not pool:
        return None
    cursor = setting.last_operator_id
    chosen = next((op for op in pool if cursor is None or op.id > cursor), pool[0])
    conv.assigned_operator_id = chosen.id
    setting.last_operator_id = chosen.id
    setting.updated_at = datetime.utcnow()
    session.add(setting)
    return chosen


def match_sla_policy(session: Session, client_id: int, department_id: int | None, priority: str) -> SlaPolicy | None:
    """The most specific active policy wins: department+priority > department > priority >
    generic. Same specificity ties break on the oldest policy, so the choice is stable."""
    policies = session.exec(
        select(SlaPolicy)
        .where(SlaPolicy.client_id == client_id, SlaPolicy.active.is_(True))
        .order_by(SlaPolicy.id)
    ).all()
    best, best_score = None, -1
    for policy in policies:
        if policy.department_id is not None and policy.department_id != department_id:
            continue
        if policy.priority and policy.priority != priority:
            continue
        score = (2 if policy.department_id is not None else 0) + (1 if policy.priority else 0)
        if score > best_score:
            best, best_score = policy, score
    return best


def apply_sla(session: Session, conv: Conversation, *, start: bool = False) -> None:
    """(Re)compute the SLA stamps of a conversation. `start=True` starts the clock if it isn't
    running yet. Recomputing after a priority/department change re-matches the policy and moves
    the deadlines, always measured from the original start. Nothing is committed here."""
    if start and conv.sla_started_at is None:
        conv.sla_started_at = datetime.utcnow()
    if conv.sla_started_at is None:
        return
    policy = match_sla_policy(session, conv.client_id, conv.department_id, conv.priority)
    started = conv.sla_started_at
    conv.sla_policy_id = policy.id if policy else None
    conv.first_response_due_at = conv.first_response_warn_at = None
    conv.resolution_due_at = conv.resolution_warn_at = None
    schedule = session.exec(select(SupportSchedule).where(
        SupportSchedule.client_id == conv.client_id,
        SupportSchedule.enabled == True,  # noqa: E712
    )).first()

    def deadline(minutes: float) -> datetime:
        if schedule is None:
            return started + timedelta(minutes=minutes)
        return business_hours.add_business_minutes(
            started, minutes,
            weekdays=schedule.weekdays,
            start_time=schedule.start_time,
            end_time=schedule.end_time,
            timezone_name=schedule.timezone,
            closed_dates=json.loads(schedule.closed_dates or "[]"),
            include_italian_holidays=schedule.include_italian_holidays,
        )

    if policy and policy.first_response_minutes > 0:
        conv.first_response_due_at = deadline(policy.first_response_minutes)
        conv.first_response_warn_at = deadline(policy.first_response_minutes * SLA_WARN_RATIO)
    if policy and policy.resolution_minutes > 0:
        conv.resolution_due_at = deadline(policy.resolution_minutes)
        conv.resolution_warn_at = deadline(policy.resolution_minutes * SLA_WARN_RATIO)
    # a deadline moved back into the future is a new target: allow it to alert again
    now = datetime.utcnow()
    if conv.first_response_due_at is None or conv.first_response_due_at > now:
        conv.first_response_breach_notified = False
    if conv.resolution_due_at is None or conv.resolution_due_at > now:
        conv.resolution_breach_notified = False


ROUTING_MODES = ("off", "round_robin")


def require_department(session: Session, client_id: int, department_id: int) -> Department:
    department = session.get(Department, department_id)
    if not department or department.client_id != client_id:
        raise HTTPException(404, "department not found")
    return department


def support_schedule_payload(row: SupportSchedule | None) -> dict:
    if row is None:
        return {
            "enabled": False, "weekdays": [1, 2, 3, 4, 5], "start_time": "09:00",
            "end_time": "18:00", "timezone": "Europe/Rome", "source": "panel",
            "closed_dates": [],
            "include_italian_holidays": False,
        }
    return {
        "enabled": row.enabled,
        "weekdays": business_hours.parse_weekdays(row.weekdays),
        "start_time": row.start_time,
        "end_time": row.end_time,
        "timezone": row.timezone,
        "closed_dates": json.loads(row.closed_dates or "[]"),
        "include_italian_holidays": row.include_italian_holidays,
        "source": row.source,
        "updated_at": _iso(row.updated_at),
    }


def validated_support_schedule(body: dict) -> dict:
    try:
        weekdays = business_hours.parse_weekdays(body.get("weekdays", []))
        start_time = business_hours.parse_time(body.get("start_time", "")).strftime("%H:%M")
        end_time = business_hours.parse_time(body.get("end_time", "")).strftime("%H:%M")
        timezone_name = business_hours.validate_timezone(body.get("timezone", ""))
        closed_dates = business_hours.parse_closed_dates(body.get("closed_dates", []))
        if start_time == end_time:
            raise ValueError("L’orario di apertura e chiusura non può coincidere")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "enabled": bool(body.get("enabled", False)),
        "weekdays": weekdays,
        "start_time": start_time,
        "end_time": end_time,
        "timezone": timezone_name,
        "closed_dates": [item.isoformat() for item in closed_dates],
        "include_italian_holidays": bool(body.get("include_italian_holidays", False)),
    }


def save_support_schedule(session: Session, client_id: int, body: dict, source: str) -> SupportSchedule:
    clean = validated_support_schedule(body)
    row = session.exec(select(SupportSchedule).where(SupportSchedule.client_id == client_id)).first()
    if row is None:
        row = SupportSchedule(client_id=client_id)
    row.enabled = clean["enabled"]
    row.weekdays = ",".join(str(day) for day in clean["weekdays"])
    row.start_time = clean["start_time"]
    row.end_time = clean["end_time"]
    row.timezone = clean["timezone"]
    # WordPress owns weekly hours and timezone, while exceptional closures are managed in
    # the panel. Older plugin payloads must never erase them during an automatic sync.
    if "closed_dates" in body or row.id is None:
        row.closed_dates = json.dumps(clean["closed_dates"])
    if "include_italian_holidays" in body or row.id is None:
        row.include_italian_holidays = clean["include_italian_holidays"]
    row.source = source
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    for conversation in session.exec(select(Conversation).where(
        Conversation.client_id == client_id,
        Conversation.sla_started_at.is_not(None),
        Conversation.closed_at.is_(None),
    )).all():
        apply_sla(session, conversation)
        session.add(conversation)
    session.commit()
    session.refresh(row)
    return row
