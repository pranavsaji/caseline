"""Outbound messaging providers behind one interface (guiding principle #3).

Phase 1 needs SMS only as a tool the agent can invoke (booking
confirmations, follow-up links). ``LoggingSMSProvider`` is the local/dev
default; ``TwilioSMSProvider`` is the real transport, config-selected.
Full SMS *threads* (inbound, conversation policy) are Phase 3.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger("caseline.messaging")


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


def make_sms_provider() -> SMSProvider:
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    if sid and token and from_number:
        return TwilioSMSProvider(sid, token, from_number)
    return LoggingSMSProvider()
