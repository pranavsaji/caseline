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


def make_sms_provider() -> SMSProvider:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if sid and token and from_number:
        return TwilioSMSProvider(sid, token, from_number)
    return LoggingSMSProvider()
