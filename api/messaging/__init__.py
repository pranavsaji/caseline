"""Outbound messaging providers behind one interface (guiding principle #3).

Phase 1 needs SMS only as a tool the agent can invoke (booking
confirmations, follow-up links). ``LoggingSMSProvider`` is the local/dev
default; ``TwilioSMSProvider`` is the real transport, config-selected.
Phase 3 adds full SMS *threads* (inbound webhook + conversation policy in
``api/orchestration/threads.py``) and the email channel behind
``EmailProvider`` — the thread engine is channel-agnostic and picks the
transport per thread."""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger("caseline.messaging")


def normalize_phone(raw: str | None) -> str | None:
    """Best-effort E.164 normalization (US-default). Returns None when the input
    can't be a valid number — callers must handle that rather than hand a
    malformed 'To' to Twilio (which 422s and, unguarded, surfaces as a 500).

    Speech-to-text often drops or mangles digits ("124830370"), so validating
    here keeps a bad transcription from crashing the send."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("+"):
        digits = re.sub(r"\D", "", raw)
        return f"+{digits}" if 11 <= len(digits) <= 15 else None
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:  # bare US number
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return None


class SMSProvider(ABC):
    name: str

    @abstractmethod
    def send(self, to: str, body: str, from_number: str | None = None) -> str:
        """Send an SMS; returns a provider message id."""


class LoggingSMSProvider(SMSProvider):
    name = "logging"

    def __init__(self) -> None:
        self.sent: list[dict] = []  # inspectable by tests and local dev

    def send(self, to: str, body: str, from_number: str | None = None) -> str:
        message_id = f"log-{len(self.sent) + 1}"
        self.sent.append({"id": message_id, "to": to, "from": from_number, "body": body})
        logger.info("SMS (logged, not sent) to=%s body=%r", to, body)
        return message_id


class TwilioSMSProvider(SMSProvider):
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self._sid = account_sid
        self._auth = (account_sid, auth_token)
        self._from = from_number

    def send(self, to: str, body: str, from_number: str | None = None) -> str:
        r = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json",
            auth=self._auth,
            data={"To": to, "From": from_number or self._from, "Body": body},
            timeout=10.0,
        )
        r.raise_for_status()
        return r.json()["sid"]


class PlivoSMSProvider(SMSProvider):
    """Plivo Messages API. Same seam as Twilio — config-selected in
    ``make_sms_provider``. Plivo's src/dst want bare digits (no leading '+'),
    so we strip it; the returned message_uuid is the provider id."""

    name = "plivo"

    def __init__(self, auth_id: str, auth_token: str, from_number: str):
        self._auth_id = auth_id
        self._auth = (auth_id, auth_token)
        self._from = from_number

    @staticmethod
    def _digits(number: str | None) -> str:
        return re.sub(r"\D", "", number or "")

    def send(self, to: str, body: str, from_number: str | None = None) -> str:
        r = httpx.post(
            f"https://api.plivo.com/v1/Account/{self._auth_id}/Message/",
            auth=self._auth,
            json={
                "src": self._digits(from_number or self._from),
                "dst": self._digits(to),
                "text": body,
            },
            timeout=10.0,
        )
        # Plivo puts the actionable reason in the JSON body ("error"), not the
        # status line — e.g. a 400 for an unregistered A2P 10DLC campaign looks
        # identical to a 400 for a malformed number unless you read it. Fold it
        # into the exception message so the tool layer can log something useful.
        if r.is_error:
            try:
                detail = r.json().get("error") or r.text
            except ValueError:
                detail = r.text
            raise httpx.HTTPStatusError(
                f"Plivo {r.status_code}: {detail}", request=r.request, response=r
            )
        # Plivo returns {"message_uuid": ["<id>"], "api_id": "..."}.
        uuids = r.json().get("message_uuid") or []
        return uuids[0] if uuids else r.json().get("api_id", "plivo-sent")


class EmailProvider(ABC):
    name: str

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> str:
        """Send an email; returns a provider message id."""


class LoggingEmailProvider(EmailProvider):
    name = "logging"

    def __init__(self) -> None:
        self.sent: list[dict] = []  # inspectable by tests and local dev

    def send(self, to: str, subject: str, body: str) -> str:
        message_id = f"log-email-{len(self.sent) + 1}"
        self.sent.append({"id": message_id, "to": to, "subject": subject, "body": body})
        logger.info("EMAIL (logged, not sent) to=%s subject=%r", to, subject)
        return message_id


class SMTPEmailProvider(EmailProvider):
    name = "smtp"

    def __init__(self, host: str, port: int, username: str, password: str, from_address: str):
        self._host, self._port = host, port
        self._username, self._password = username, password
        self._from = from_address

    def send(self, to: str, subject: str, body: str) -> str:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._from, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(self._username, self._password)
            smtp.send_message(msg)
        return msg["Message-Id"] or f"smtp-{to}"


def make_email_provider() -> EmailProvider:
    host = os.getenv("CASELINE_SMTP_HOST")
    if host:
        return SMTPEmailProvider(
            host=host,
            port=int(os.getenv("CASELINE_SMTP_PORT", "587")),
            username=os.getenv("CASELINE_SMTP_USERNAME", ""),
            password=os.getenv("CASELINE_SMTP_PASSWORD", ""),
            from_address=os.getenv("CASELINE_SMTP_FROM", "intake@caseline.app"),
        )
    return LoggingEmailProvider()


def sms_outbound_enabled() -> bool:
    """Whether the agent may OFFER to send an SMS.

    Credentials being present is not the same as being allowed to send: a US
    long code still needs an approved A2P 10DLC campaign, and that approval is
    invisible until a send is rejected. Rather than let the agent promise a
    text and then apologize, this gate lets us turn the offer off until the
    registration clears. Flip `CASELINE_SMS_ENABLED=true` once it does.
    """
    return os.getenv("CASELINE_SMS_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def make_sms_provider() -> SMSProvider:
    # Plivo preferred when its credentials are present (the firm's chosen
    # provider), then Twilio, else the local logging no-op. All three satisfy
    # the same SMSProvider seam, so nothing downstream changes.
    plivo_id = os.getenv("PLIVO_AUTH_ID")
    plivo_token = os.getenv("PLIVO_AUTH_TOKEN")
    plivo_from = os.getenv("PLIVO_FROM_NUMBER")
    if plivo_id and plivo_token and plivo_from:
        return PlivoSMSProvider(plivo_id, plivo_token, plivo_from)
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if sid and token and from_number:
        return TwilioSMSProvider(sid, token, from_number)
    return LoggingSMSProvider()
