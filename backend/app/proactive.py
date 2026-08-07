"""Proactive messages: triggers, frequency and how a rule is described to a caller.

Shared by the automations (which manage rules) and the widget (which decides whether to show
one), so neither owns it. The A/B thresholds live here too: declaring a winner is a statistical
claim, and the numbers behind it should be visible in one place.
"""
import math

from .db import ProactiveExperiment, ProactiveRule

MAX_PROACTIVE_MESSAGE_CHARS = 300
PROACTIVE_AB_MIN_IMPRESSIONS = 30
PROACTIVE_AB_Z_THRESHOLD = 1.96  # two-sided 95% confidence
PROACTIVE_FREQUENCIES = ("once_per_session", "once_per_day", "always")
PROACTIVE_TRIGGERS = ("url", "time_on_page", "exit_intent", "cart")


def ab_result(rule: ProactiveRule) -> dict:
    """Two-proportion z-test. Never declares a winner before both samples are useful."""
    if not rule.message_b:
        return {"status": "not_configured", "winner": None, "lift_percent": None}
    if min(rule.impressions, rule.impressions_b) < PROACTIVE_AB_MIN_IMPRESSIONS:
        remaining = max(
            PROACTIVE_AB_MIN_IMPRESSIONS - rule.impressions,
            PROACTIVE_AB_MIN_IMPRESSIONS - rule.impressions_b,
        )
        return {"status": "collecting", "winner": None, "lift_percent": None, "remaining": remaining}
    rate_a = rule.engagements / rule.impressions
    rate_b = rule.engagements_b / rule.impressions_b
    pooled = (rule.engagements + rule.engagements_b) / (rule.impressions + rule.impressions_b)
    error = math.sqrt(pooled * (1 - pooled) * (1 / rule.impressions + 1 / rule.impressions_b))
    z_score = abs(rate_a - rate_b) / error if error else 0.0
    if z_score < PROACTIVE_AB_Z_THRESHOLD:
        return {"status": "inconclusive", "winner": None, "lift_percent": None, "z_score": round(z_score, 2)}
    winner = "a" if rate_a > rate_b else "b"
    winner_rate, loser_rate = (rate_a, rate_b) if winner == "a" else (rate_b, rate_a)
    lift = round((winner_rate / loser_rate - 1) * 100, 1) if loser_rate else None
    return {"status": "winner", "winner": winner, "lift_percent": lift, "z_score": round(z_score, 2)}


def rule_payload(rule: ProactiveRule, *, public: bool = False) -> dict:
    data = {
        "id": rule.id,
        "trigger_type": rule.trigger_type,
        "url_pattern": rule.url_pattern,
        "delay_seconds": rule.delay_seconds,
        "message": rule.message,
        "message_b": rule.message_b,
        "frequency": rule.frequency,
    }
    if public:
        return data
    return {
        **data,
        "name": rule.name,
        "active": rule.active,
        "position": rule.position,
        "impressions": rule.impressions,
        "engagements": rule.engagements,
        "engagement_rate": round(rule.engagements / rule.impressions, 3) if rule.impressions else None,
        "impressions_b": rule.impressions_b,
        "engagements_b": rule.engagements_b,
        "engagement_rate_b": round(rule.engagements_b / rule.impressions_b, 3) if rule.impressions_b else None,
        "ab_test": ab_result(rule),
    }
