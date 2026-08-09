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

import json
import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

from .logging_config import log
from .usage import record_message

logger = logging.getLogger("wpai.email")

# Provider: "smtp" (default) or "brevo_api". On hosts that block outbound SMTP ports (e.g.
# Railway blocks 25/465/587/2525), use "brevo_api" to send over HTTPS/443 instead.
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").lower()

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER or "no-reply@wp-aissistant.local"
SMTP_TLS = os.getenv("SMTP_TLS", "true").lower()  # "true" (STARTTLS) | "ssl" | "false"
EMAIL_TIMEOUT_SECONDS = float(os.getenv("EMAIL_TIMEOUT_SECONDS", "10"))

# Brevo transactional API (HTTPS) — used when EMAIL_PROVIDER=brevo_api
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "WP AIssistant")
SUPPORT_EMAIL_ADDRESS = os.getenv("SUPPORT_EMAIL_ADDRESS", "support@wpaissistant.it").strip()


def _header(value: str) -> str:
    """Keep provider-controlled thread metadata from becoming an email header injection."""
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())


def enabled() -> bool:
    """True when the selected provider is configured enough to actually send. When False,
    send_email() logs the message instead — handy in dev, but prod must configure a provider."""
    if EMAIL_PROVIDER == "brevo_api":
        return bool(BREVO_API_KEY)
    return bool(SMTP_HOST)


def panel_url() -> str:
    explicit = os.getenv("PANEL_PUBLIC_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    origins = os.getenv("PANEL_ORIGINS", "http://localhost:5173")
    first = next((o.strip() for o in origins.split(",") if o.strip()), "http://localhost:5173")
    return first.rstrip("/")


def send_email(
    to: str,
    subject: str,
    body: str,
    *,
    headers: dict[str, str] | None = None,
    reply_to: str = "",
    client_id: int | None = None,
) -> bool:
    """Send a plain-text email via the configured provider. Returns True on success (or when
    logged-only in dev), False on a delivery failure. Never raises — callers branch on the bool.

    `client_id` attribuisce il costo del messaggio a un tenant. Va passato quando l'email parte
    per il traffico di quel tenant (risposta al visitatore, canale email, azione di workflow);
    va lasciato vuoto per le email che riguardano l'account e non il servizio erogato ai suoi
    visitatori — verifica indirizzo, reset password, avvisi di fatturazione — che sono spesa di
    piattaforma. Il conteggio sta qui, all'unica strozzatura da cui passa ogni invio, e non nei
    dodici punti che la chiamano: uno dimenticato sarebbe un buco silenzioso nel margine.
    """
    subject = _header(subject)
    headers = {key: _header(value) for key, value in (headers or {}).items() if _header(value)} or None
    if not enabled():
        # dev/staging fallback: make the link readable without a configured provider
        log(logger, logging.INFO, "email.not_configured_logged", to=to, subject=subject, body=body)
        return True  # non contato: senza provider non è partito nulla e nulla è costato
    if EMAIL_PROVIDER == "brevo_api":
        sent = _send_brevo_api(to, subject, body, headers=headers, reply_to=reply_to)
    else:
        sent = _send_smtp(to, subject, body, headers=headers, reply_to=reply_to)
    record_message(client_id, "email", ok=sent)
    return sent


def _send_smtp(to: str, subject: str, body: str, *, headers: dict[str, str] | None = None, reply_to: str = "") -> bool:
    try:
        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = _header(reply_to)
        for key, value in (headers or {}).items():
            msg[key] = value
        msg.set_content(body)
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
        log(logger, logging.INFO, "email.sent", provider="smtp", to=to, subject=subject)
        return True
    except Exception as exc:  # noqa: BLE001 — report failure via the return value, never crash
        log(logger, logging.ERROR, "email.send_failed", provider="smtp", to=to, subject=subject, error=str(exc))
        return False


def _send_brevo_api(to: str, subject: str, body: str, *, headers: dict[str, str] | None = None, reply_to: str = "") -> bool:
    """Send over Brevo's transactional API (HTTPS/443) — works where outbound SMTP is blocked."""
    payload = {
        "sender": {"email": SMTP_FROM, "name": EMAIL_FROM_NAME},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
    }
    if headers:
        payload["headers"] = headers
    if reply_to:
        payload["replyTo"] = {"email": _header(reply_to)}
    req = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode(),
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=EMAIL_TIMEOUT_SECONDS) as resp:
            resp.read()
        log(logger, logging.INFO, "email.sent", provider="brevo_api", to=to, subject=subject)
        return True
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        if isinstance(exc, urllib.error.HTTPError):
            try:
                detail = f"{exc.code} {exc.read().decode()[:300]}"  # surface Brevo's error body
            except Exception:  # noqa: BLE001
                pass
        log(logger, logging.ERROR, "email.send_failed", provider="brevo_api", to=to, subject=subject, error=detail)
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


def send_visitor_reply(to: str, client_name: str, page_url: str | None, client_id: int | None = None) -> bool:
    """Notify a visitor that a human operator replied to their conversation."""
    if page_url:
        cta = f"Riapri la chat per leggerla e continuare la conversazione:\n{page_url}\n\n"
    else:
        cta = "Torna sul sito e riapri la chat per leggerla.\n\n"
    body = f"Hai ricevuto una risposta dal supporto di {client_name}.\n\n{cta}Grazie!\n"
    return send_email(to, f"Nuova risposta dal supporto — {client_name}", body, client_id=client_id)


def send_channel_reply(to: str, client_name: str, subject: str, body: str, thread_id: str = "", client_id: int | None = None) -> bool:
    """Deliver a panel reply directly into an email-channel thread."""
    clean_subject = _header(subject) or f"Supporto — {client_name}"
    if not clean_subject.lower().startswith("re:"):
        clean_subject = f"Re: {clean_subject}"
    clean_thread_id = _header(thread_id)
    headers = {"In-Reply-To": clean_thread_id, "References": clean_thread_id} if clean_thread_id else None
    return send_email(to, clean_subject, body, headers=headers, reply_to=SUPPORT_EMAIL_ADDRESS, client_id=client_id)


def _billing_link() -> str:
    """Where the customer goes to fix a billing problem: the panel's own billing section."""
    return f"{panel_url()}/?section=billing"


def _on_date(value, prefix: str = " il") -> str:
    """' il 12/09/2026' when the date is known, '' otherwise — never an invented deadline.

    `prefix` perché la stessa data entra in frasi diverse ("fino al", ", il"): senza, la
    preposizione andrebbe scritta fuori e comparirebbe anche quando la data non c'è.
    """
    return f"{prefix} {value.strftime('%d/%m/%Y')}" if value else ""


def send_payment_failed(to: str) -> bool:
    """Warn the tenant that a charge failed, while Stripe is still retrying it."""
    body = (
        "Non siamo riusciti ad addebitare il tuo abbonamento WP AIssistant.\n\n"
        "Il servizio resta attivo mentre riproviamo il pagamento. Per evitare interruzioni, "
        "aggiorna il metodo di pagamento dal pannello:\n"
        f"{_billing_link()}\n\n"
        "Se hai già risolto, ignora questa email.\n"
    )
    return send_email(to, "Pagamento non riuscito — WP AIssistant", body)


def send_trial_ending(to: str, trial_end=None) -> bool:
    """Remind the tenant that the free trial is about to convert into a paid subscription."""
    body = (
        f"Il tuo periodo di prova di WP AIssistant termina{_on_date(trial_end)}.\n\n"
        "Alla scadenza attiveremo l'abbonamento sul metodo di pagamento che hai registrato. "
        "Puoi cambiare piano o disdire in qualsiasi momento dal pannello:\n"
        f"{_billing_link()}\n"
    )
    return send_email(to, "La prova sta per terminare — WP AIssistant", body)


def send_cancellation_scheduled(to: str, ends_at=None, retention_days: int = 90) -> bool:
    """Confirm a cancellation requested from the billing portal, before it takes effect."""
    body = (
        f"Abbiamo registrato la disdetta del tuo abbonamento WP AIssistant.\n\n"
        f"Il servizio resta attivo fino alla fine del periodo già pagato{_on_date(ends_at)}. "
        "Dopo quella data l'assistente smette di rispondere ai visitatori del tuo sito, "
        f"ma i tuoi dati restano al loro posto ancora {retention_days} giorni: conversazioni, "
        "knowledge base e impostazioni ti aspettano se cambi idea, e la riattivazione è "
        "immediata.\n\n"
        "Se hai cambiato idea puoi riattivare dal pannello:\n"
        f"{_billing_link()}\n"
    )
    return send_email(to, "Disdetta registrata — WP AIssistant", body)


def send_subscription_canceled(to: str, deletion_at=None, retention_days: int = 90) -> bool:
    """Tell the tenant the paid subscription has ended and the assistant is now suspended."""
    body = (
        "Il tuo abbonamento WP AIssistant è terminato e l'assistente ha smesso di rispondere "
        "ai visitatori del tuo sito.\n\n"
        f"I tuoi dati restano disponibili ancora {retention_days} giorni"
        f"{_on_date(deletion_at, prefix=', fino al')}: conversazioni, knowledge base e "
        "impostazioni sono al loro posto e la riattivazione è immediata, senza rifare nulla.\n\n"
        "Puoi riattivare quando vuoi dal pannello:\n"
        f"{_billing_link()}\n"
    )
    return send_email(to, "Abbonamento terminato — WP AIssistant", body)


def send_deletion_reminder(to: str, days_left: int, deletion_at=None) -> bool:
    """Avvisa che i dati stanno per essere eliminati definitivamente.

    Scritta perché si possa agire leggendo solo la prima riga: chi la riceve ha già disdetto e
    non sta guardando il pannello. Il numero di giorni sta nell'oggetto per la stessa ragione.
    """
    giorni = "giorno" if days_left == 1 else "giorni"
    body = (
        f"Fra {days_left} {giorni} i dati del tuo account WP AIssistant verranno eliminati "
        f"definitivamente{_on_date(deletion_at, prefix=', il')}.\n\n"
        "Riguarda conversazioni, knowledge base, contatti e impostazioni: dopo quella data non "
        "sono più recuperabili, da noi né da te.\n\n"
        "Se ti servono ancora, basta riattivare un piano dal pannello — la cancellazione si "
        "annulla e ritrovi tutto com'era:\n"
        f"{_billing_link()}\n"
    )
    return send_email(to, f"Fra {days_left} {giorni} i tuoi dati verranno eliminati — WP AIssistant", body)


def send_test(to: str) -> bool:
    """Send a diagnostic email so an admin can confirm SMTP works end-to-end."""
    return send_email(
        to,
        "Email di test — WP AIssistant",
        "Se leggi questo messaggio, la configurazione SMTP di WP AIssistant funziona. 🎉\n",
    )


def config_status() -> dict:
    """Non-secret email config summary for the admin health/panel (never exposes secrets)."""
    host = BREVO_API_URL if EMAIL_PROVIDER == "brevo_api" else SMTP_HOST
    return {"configured": enabled(), "provider": EMAIL_PROVIDER, "host": host, "from": SMTP_FROM}
