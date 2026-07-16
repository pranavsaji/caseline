"""Rules-engine tests: pure logic, no I/O."""

from datetime import date, timedelta

from api.qualification import (
    DECISION_DECLINE,
    DECISION_QUALIFIED,
    DECISION_REFER_OUT,
    QualificationConfig,
    qualify,
)

TODAY = date(2026, 7, 16)


def days_ago(n: int) -> str:
    return (TODAY - timedelta(days=n)).isoformat()


def test_recent_serious_injury_qualifies():
    result = qualify(days_ago(30), "whiplash", True, True, today=TODAY)
    assert result.decision == DECISION_QUALIFIED
    assert any("within limitations" in r for r in result.reasons)


def test_statute_of_limitations_declines():
    result = qualify(days_ago(731), "broken arm", True, True, today=TODAY)
    assert result.decision == DECISION_DECLINE
    assert any("statute-of-limitations" in r for r in result.reasons)


def test_exactly_at_limit_still_qualifies():
    result = qualify(days_ago(730), "broken arm", True, True, today=TODAY)
    assert result.decision == DECISION_QUALIFIED


def test_minor_injury_refers_out():
    result = qualify(days_ago(10), "Minor", False, True, today=TODAY)
    assert result.decision == DECISION_REFER_OUT


def test_no_injury_refers_out():
    result = qualify(days_ago(10), "none", False, False, today=TODAY)
    assert result.decision == DECISION_REFER_OUT


def test_unparseable_date_never_auto_declines():
    result = qualify("last summer", "spinal injury", True, True, today=TODAY)
    assert result.decision == DECISION_QUALIFIED
    assert any("needs human verification" in r for r in result.reasons)


def test_future_date_never_auto_declines():
    result = qualify(days_ago(-5), "whiplash", True, True, today=TODAY)
    assert result.decision == DECISION_QUALIFIED
    assert any("in the future" in r for r in result.reasons)


def test_unparseable_date_with_minor_injury_still_refers_out():
    result = qualify("no idea", "minor", False, False, today=TODAY)
    assert result.decision == DECISION_REFER_OUT


def test_custom_statute_config():
    config = QualificationConfig(statute_of_limitations_days=365)
    result = qualify(days_ago(400), "whiplash", True, True, config=config, today=TODAY)
    assert result.decision == DECISION_DECLINE
