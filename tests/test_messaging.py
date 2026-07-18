"""SMS provider selection + the Plivo adapter's request shape."""

import httpx
import pytest

from api.messaging import (
    LoggingSMSProvider,
    PlivoSMSProvider,
    TwilioSMSProvider,
    make_sms_provider,
)

SMS_ENV = [
    "PLIVO_AUTH_ID", "PLIVO_AUTH_TOKEN", "PLIVO_FROM_NUMBER",
    "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER",
]


@pytest.fixture
def clean_sms_env(monkeypatch):
    for key in SMS_ENV:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_no_credentials_falls_back_to_logging(clean_sms_env):
    assert isinstance(make_sms_provider(), LoggingSMSProvider)


def test_twilio_selected_when_only_twilio_set(clean_sms_env):
    clean_sms_env.setenv("TWILIO_ACCOUNT_SID", "AC")
    clean_sms_env.setenv("TWILIO_AUTH_TOKEN", "tok")
    clean_sms_env.setenv("TWILIO_FROM_NUMBER", "+13124830370")
    assert isinstance(make_sms_provider(), TwilioSMSProvider)


def test_plivo_preferred_over_twilio(clean_sms_env):
    for key in SMS_ENV:
        clean_sms_env.setenv(key, "x")
    clean_sms_env.setenv("PLIVO_FROM_NUMBER", "+12092222430")
    assert isinstance(make_sms_provider(), PlivoSMSProvider)


def test_plivo_send_posts_bare_digits_and_returns_uuid():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(202, json={"message_uuid": ["msg-123"], "api_id": "api-1"})

    transport = httpx.MockTransport(handler)
    real_post = httpx.post

    def fake_post(url, **kwargs):
        with httpx.Client(transport=transport) as c:
            return c.post(url, **kwargs)

    httpx.post = fake_post
    try:
        provider = PlivoSMSProvider("MAAUTHID", "secret", "+12092222430")
        message_id = provider.send("+1 (415) 555-0123", "Your consult is booked.")
    finally:
        httpx.post = real_post

    assert message_id == "msg-123"
    # E.164 '+' stripped for Plivo on both src and dst.
    assert captured["json"]["src"] == "12092222430"
    assert captured["json"]["dst"] == "14155550123"
    assert captured["json"]["text"] == "Your consult is booked."
    assert "/Account/MAAUTHID/Message/" in captured["url"]
