"""Typed coercion: dates, money, rates, times, durations. LLD §5 / HLD §3.1.

Day-first dates are not optional in this domain — Indian documents are overwhelmingly
day-first and a system that resolves 12/03/2026 as December silently corrupts every timeline
rule. Money is integer paise and rates are integer basis points because float arithmetic in a
compliance rule is a defect waiting to be found.
"""

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

_IST = ZoneInfo("Asia/Kolkata")

_DATE_FORMATS_DAY_FIRST = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y"]
_DATE_FORMAT_ISO = "%Y-%m-%d"

_MONEY_RE = re.compile(r"[₹Rs.\s,]*([\d,]+(?:\.\d+)?)")
_RATE_RE = re.compile(r"([\d.]+)\s*%")
_TIME_24H_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_TIME_12H_RE = re.compile(r"^(\d{1,2}):([0-5]\d)\s*([APap][Mm])$")


class NormalisationError(Exception):
    pass


def normalise_date(raw: str) -> date:
    """Day-first: '12/03/2026' -> 2026-03-12, never 2026-12-03."""
    raw = raw.strip()
    try:
        return datetime.strptime(raw, _DATE_FORMAT_ISO).date()
    except ValueError:
        pass
    for fmt in _DATE_FORMATS_DAY_FIRST:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise NormalisationError(f"cannot parse date: {raw!r}")


def normalise_time(raw: str) -> time:
    raw = raw.strip()
    if m := _TIME_24H_RE.match(raw):
        return time(int(m.group(1)), int(m.group(2)))
    if m := _TIME_12H_RE.match(raw):
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "pm":
            hour += 12
        return time(hour, int(m.group(2)))
    raise NormalisationError(f"cannot parse time: {raw!r}")


def normalise_datetime(raw_date: str, raw_time: str | None = None) -> datetime:
    """Combines a date and an optional time, localised to Asia/Kolkata (registry
    normalisation: timezone: Asia/Kolkata, assume_local: true)."""
    d = normalise_date(raw_date)
    t = normalise_time(raw_time) if raw_time else time(0, 0)
    return datetime.combine(d, t, tzinfo=_IST)


def parse_full_datetime(raw: str) -> datetime:
    """Parses a single combined string like '03/09/2026 20:10' into an IST-aware datetime."""
    raw = raw.strip()
    parts = raw.split(maxsplit=1)
    if len(parts) == 2:
        return normalise_datetime(parts[0], parts[1])
    return normalise_datetime(raw)


def normalise_money_to_paise(raw: str) -> int:
    """'₹1,20,000' -> 12000000 paise. Rejects anything that isn't a plain numeral."""
    cleaned = raw.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    cleaned = cleaned.replace(",", "")
    m = re.fullmatch(r"(\d+)(?:\.(\d{1,2}))?", cleaned)
    if not m:
        raise NormalisationError(f"cannot parse money: {raw!r}")
    rupees = int(m.group(1))
    paise_fraction = m.group(2) or "0"
    paise_fraction = (paise_fraction + "00")[:2]
    return rupees * 100 + int(paise_fraction)


def normalise_rate_to_bps(raw: str) -> int:
    """'18.5%' -> 1850 bps. '18.5% p.a.' -> 1850 (the p.a. qualifier is stripped)."""
    cleaned = raw.strip()
    m = _RATE_RE.search(cleaned)
    if not m:
        raise NormalisationError(f"cannot parse rate: {raw!r}")
    value = float(m.group(1))
    bps = round(value * 100)
    return bps


def normalise_duration_days(raw: str) -> int:
    """Accepts a bare integer, 'N days', 'N months' (x30, approximate), or 'N years' (x365)."""
    cleaned = raw.strip().lower()
    m = re.match(r"(\d+)\s*(day|days|month|months|year|years)?$", cleaned)
    if not m:
        raise NormalisationError(f"cannot parse duration: {raw!r}")
    value = int(m.group(1))
    unit = m.group(2) or "days"
    if unit.startswith("month"):
        return value * 30
    if unit.startswith("year"):
        return value * 365
    return value
