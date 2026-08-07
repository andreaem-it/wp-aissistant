"""Assignment and SLA: who a conversation goes to, and by when.

The rules that turn an escalation into someone's job — the tenant's routing mode, the queue of
operators, and the deadlines from the most specific matching policy. Shared by the inbox, the
channels and the automations, so it lives outside any one of them.
"""
import json
import logging
import os
from datetime import datetime, timedelta

from sqlmodel import Session, select

from . import business_hours
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
