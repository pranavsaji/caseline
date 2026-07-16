"""TCPA outbound-contact policy: consent gate, quiet hours, opt-out keywords.

The chaser initiates contact, so the legal posture flips from Phase 2's
recording consent to prior-express-consent + 8am-9pm recipient-local quiet
hours. No consent is a hard deny; quiet hours defer, never drop."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from api.compliance.outbound import (
    is_help,
    is_opt_out,
    next_allowed_time,
    opt_out_confirmation,
    outbound_policy,
)

CA_NUMBER = "+14155550123"  # 415 -> CA -> America/Los_Angeles
TOLL_FREE = "+18005551234"  # unmapped -> firm timezone fallback


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_no_consent_is_a_hard_deny():
    policy = outbound_policy(CA_NUMBER, consent=False, now=utc(2026, 7, 16, 18))
    assert not policy.allowed
    assert policy.defer_until is None  # time will not fix a consent problem
    assert "consent" in policy.reason


def test_never_asked_is_the_same_as_no():
    assert not outbound_policy(CA_NUMBER, consent=None, now=utc(2026, 7, 16, 18)).allowed


def test_consented_inside_window_is_allowed():
    # 18:00 UTC in July = 11:00 in Los Angeles
    policy = outbound_policy(CA_NUMBER, consent=True, now=utc(2026, 7, 16, 18))
    assert policy.allowed
    assert policy.recipient_state == "CA"


def test_late_night_defers_to_next_morning_recipient_local():
    # 06:00 UTC = 23:00 previous evening in LA
    policy = outbound_policy(CA_NUMBER, consent=True, now=utc(2026, 7, 16, 6))
    assert not policy.allowed
    assert policy.defer_until is not None
    local = policy.defer_until.astimezone(ZoneInfo("America/Los_Angeles"))
    assert (local.hour, local.minute) == (8, 0)
    assert policy.defer_until > utc(2026, 7, 16, 6)


def test_early_morning_defers_to_same_day_8am():
    # 11:00 UTC = 04:00 in LA -> defer to 08:00 LA the same day (15:00 UTC)
    policy = outbound_policy(CA_NUMBER, consent=True, now=utc(2026, 7, 16, 11))
    assert not policy.allowed
    assert policy.defer_until == utc(2026, 7, 16, 15)


def test_unknown_number_falls_back_to_firm_timezone():
    # 18:00 UTC = 13:00 in Chicago -> allowed under the firm-tz fallback
    policy = outbound_policy(
        TOLL_FREE, consent=True, firm_timezone="America/Chicago", now=utc(2026, 7, 16, 18)
    )
    assert policy.allowed
    assert policy.recipient_state is None


def test_next_allowed_time_passes_through_when_already_allowed():
    now = utc(2026, 7, 16, 18)
    assert next_allowed_time(CA_NUMBER, "America/Chicago", now) == now


def test_opt_out_keywords_are_whole_message_matches():
    assert is_opt_out("STOP")
    assert is_opt_out("stop.")
    assert is_opt_out("  Unsubscribe! ")
    assert is_opt_out("opt out")
    assert not is_opt_out("please don't stop calling me")
    assert not is_opt_out("I want to stop the treatment next week")


def test_help_keyword_and_replies():
    assert is_help("HELP")
    assert not is_help("I need help with my case")
    assert "unsubscribed" in opt_out_confirmation("Bluebonnet Injury Law")
