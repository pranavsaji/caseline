"""Outbound-contact compliance (Phase 3): TCPA consent + quiet hours + opt-out.

The Digital Lead Chaser initiates contact, which flips the compliance
posture: inbound callers consent by calling; outbound targets must have
given *prior express consent* (TCPA — for automated/prerecorded calls and
texts the bar is prior express written consent, which the webform must
capture). No consent, no automated outbound — ever.

Quiet hours: TCPA/TSR forbid calls before 8am or after 9pm in the recipient's
local time. We resolve the recipient's timezone from their area-code state
(reusing the Phase 2 consent map); unknown numbers fall back to the firm's
timezone, and a blocked send is *deferred* to the next allowed window rather
than dropped — speed-to-lead matters, but not enough to break the law.

Opt-out: CTIA reserved keywords (STOP et al.) revoke consent immediately and
unconditionally; HELP gets an informational reply. Both are handled before
any orchestration logic sees the message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from api.compliance.consent import AREA_CODE_STATE, area_code_of

QUIET_HOURS_START = 21  # no outbound at/after 9pm recipient-local
QUIET_HOURS_END = 8  # no outbound before 8am recipient-local

# CTIA reserved opt-out / help keywords. Matching is whole-message (after
# trimming punctuation), not substring — "please don't stop calling" is not
# an opt-out, "STOP" is.
STOP_KEYWORDS = frozenset(
    {"stop", "stopall", "stop all", "unsubscribe", "cancel", "end", "quit", "revoke", "optout", "opt out"}
)
HELP_KEYWORDS = frozenset({"help", "info"})

# Primary IANA timezone per state — deliberately the *most populous* zone.
# States spanning zones get their dominant one; the 8am–9pm window plus the
# one-hour maximum skew keeps every resolution inside the legal window.
STATE_TIMEZONES: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DE": "America/New_York", "DC": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}


@dataclass(frozen=True)
class OutboundPolicy:
    allowed: bool
    reason: str
    recipient_state: str | None = None
    # When quiet hours block the send, the next legal send time; None means
    # allowed now or denied outright (no consent — time won't fix that).
    defer_until: datetime | None = None


def _recipient_zone(to_number: str | None, firm_timezone: str) -> tuple[str | None, ZoneInfo]:
    code = area_code_of(to_number)
    state = AREA_CODE_STATE.get(code) if code else None
    tz_name = STATE_TIMEZONES.get(state) if state else None
    return state, ZoneInfo(tz_name or firm_timezone)


def next_allowed_time(to_number: str | None, firm_timezone: str, now: datetime) -> datetime:
    """The earliest instant >= now inside the recipient's 8am–9pm window."""
    _, zone = _recipient_zone(to_number, firm_timezone)
    local = now.astimezone(zone)
    if local.hour >= QUIET_HOURS_START:
        local = (local + timedelta(days=1)).replace(hour=QUIET_HOURS_END, minute=0, second=0, microsecond=0)
    elif local.hour < QUIET_HOURS_END:
        local = local.replace(hour=QUIET_HOURS_END, minute=0, second=0, microsecond=0)
    return local


def outbound_policy(
    to_number: str | None,
    *,
    consent: bool | None,
    firm_timezone: str = "America/Chicago",
    now: datetime | None = None,
) -> OutboundPolicy:
    """Decide whether an automated outbound contact may happen right now.

    ``consent`` is the contact's recorded prior-express-consent flag; None
    (never asked) is treated exactly like False — consent is opt-in, never
    assumed.
    """
    if not consent:
        return OutboundPolicy(
            allowed=False,
            reason="no prior express consent on file (TCPA) — route to manual follow-up",
        )
    now = now.astimezone(ZoneInfo("UTC")) if now else datetime.now(ZoneInfo("UTC"))
    state, zone = _recipient_zone(to_number, firm_timezone)
    local = now.astimezone(zone)
    if QUIET_HOURS_END <= local.hour < QUIET_HOURS_START:
        return OutboundPolicy(allowed=True, reason="consented, inside 8am-9pm window", recipient_state=state)
    return OutboundPolicy(
        allowed=False,
        reason=f"quiet hours in {zone.key} (recipient-local {local.strftime('%H:%M')})",
        recipient_state=state,
        defer_until=next_allowed_time(to_number, firm_timezone, now),
    )


def _normalized(body: str) -> str:
    return " ".join(body.strip().lower().strip(".!?,\"' ").split())


def is_opt_out(body: str) -> bool:
    """True when the message is a CTIA opt-out keyword (whole-message match)."""
    return _normalized(body) in STOP_KEYWORDS


def is_help(body: str) -> bool:
    return _normalized(body) in HELP_KEYWORDS


def opt_out_confirmation(firm_name: str) -> str:
    """CTIA-required opt-out confirmation — the one message allowed after STOP."""
    return (
        f"You have been unsubscribed from {firm_name} messages and will receive "
        "no further texts. Reply HELP for help."
    )


def help_reply(firm_name: str) -> str:
    return (
        f"{firm_name}: we help with your case intake by text. "
        "Msg&data rates may apply. Reply STOP to opt out."
    )
