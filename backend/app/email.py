"""Transactional email over SMTP (stdlib only — smtplib/email, no extra dependency).

Config via env (all optional; unset => email is *not sent*, only logged):
  SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
  SMTP_FROM (default SMTP_USER), SMTP_TLS ("true" STARTTLS default | "ssl" | "false"),
  EMAIL_TIMEOUT_SECONDS (default 10).

Point these at any provider (SendGrid/Mailgun/Postmark/Amazon SES/Gmail SMTP...).
When SMTP is not configured the message body is logged at INFO instead of sent, so
dev/staging can read reset & verification links straight from the logs without a mailbox.

Link building uses PANEL_PUBLIC_URL (the operator panel's public origin) so the emails
point at the real panel; falls back to the first PANEL_ORIGINS entry / localhost.

Unlike notify.py (best-effort webhook that must never break its caller), the auth flows
here need to know whether delivery happened: send_email() returns True/False and never
raises, and the callers decide how to react (e.g. still return 200 on /auth/forgot to
avoid user enumeration, but surface a 502 when a verification resend genuinely fails).
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from .logging_config import log

logger = logging.getLogger("wpai.email")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER or "no-reply@wp-aissistant.local"
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower()  # "true" (STARTTLS) | "ssl" | "false"
EMAIL_TIMEOUT_SECONDS = float(os.getenv("EMAIL_TIMEOUT_SECONDS", "10"))


def enabled() -> bool:
    """True when SMTP is configured enough to actually send. When False, send_email()
    logs the message instead — handy in dev, but real deployments must set SMTP_HOST."""
    return bool(SMTP_HOST)


def panel_url() -> str:
    explicit = os.getenv("PANEL_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    origins = os.getenv("PANEL_ORIGINS", "http://localhost:5173")
    first = next((o.strip() for o in origins.split(",") if o.strip()), "http://localhost:5173")
    return first.rstrip("/")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success (or when logged-only in dev),
    False on a delivery failure. Never raises — auth callers branch on the bool."""
    if not enabled():
        # dev/staging fallback: make the link readable without a configured mailbox
        log(logger, logging.INFO, "email.not_configured_logged", to=to, subject=subject, body=body)
        return True

    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if SMTP_TLS == "ssl":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=EMAIL_TIMEOUT_SECONDS, context=context) as smtp:
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=EMAIL_TIMEOUT_SECONDS) as smtp:
                if SMTP_TLS == "true":
                    smtp.starttls(context=ssl.create_default_context())
                if SMTP_USER:
                    smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.send_message(msg)
        log(logger, logging.INFO, "email.sent", to=to, subject=subject)
        return True
    except Exception as exc:  # noqa: BLE001 — report failure via the return value, never crash
        log(logger, logging.ERROR, "email.send_failed", to=to, subject=subject, error=str(exc))
        return False


# ---- Message templates (plain text; Italian to match the product's UI language) ----


def send_verification(to: str, token: str) -> bool:
    link = f"{panel_url()}/?verify={token}"
    body = (
        "Benvenuto in WP AIssistant!\n\n"
        "Conferma il tuo indirizzo email per attivare l'account:\n"
        f"{link}\n\n"
        "Se non hai creato tu questo account, ignora questa email.\n"
    )
    return send_email(to, "Conferma il tuo indirizzo email — WP AIssistant", body)


def send_password_reset(to: str, token: str) -> bool:
    link = f"{panel_url()}/?reset={token}"
    body = (
        "Hai richiesto di reimpostare la password del tuo account WP AIssistant.\n\n"
        "Apri questo link per scegliere una nuova password (scade tra 1 ora):\n"
        f"{link}\n\n"
        "Se non sei stato tu, ignora questa email: la password non verrà cambiata.\n"
    )
    return send_email(to, "Reimposta la password — WP AIssistant", body)
