"""DST-safe business-hour calculations for tenant SLA clocks."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re


def validate_timezone(value: str) -> str:
    value = str(value or "").strip()
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if match:
        hours, minutes = int(match.group(2)), int(match.group(3))
        if hours <= 14 and minutes <= 59:
            return value
        raise ValueError("Fuso orario non valido")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Fuso orario non valido") from None
    return value


def timezone_info(value: str):
    value = validate_timezone(value)
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if not match:
        return ZoneInfo(value)
    delta = timedelta(hours=int(match.group(2)), minutes=int(match.group(3)))
    return timezone(delta if match.group(1) == "+" else -delta)


def parse_time(value: str) -> time:
    try:
        hour, minute = (int(part) for part in str(value).split(":"))
        return time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        raise ValueError("Orario non valido") from None


def parse_weekdays(value) -> tuple[int, ...]:
    raw = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    try:
        days = tuple(sorted(set(int(day) for day in raw)))
    except (TypeError, ValueError):
        raise ValueError("Giorni di supporto non validi") from None
    if not days or any(day < 1 or day > 7 for day in days):
        raise ValueError("Giorni di supporto non validi")
    return days


def parse_closed_dates(value) -> tuple[date, ...]:
    raw = value if isinstance(value, (list, tuple, set)) else []
    try:
        dates = tuple(sorted(set(date.fromisoformat(str(item)) for item in raw)))
    except (TypeError, ValueError):
        raise ValueError("Data di chiusura non valida") from None
    return dates


def easter_sunday(year: int) -> date:
    """Gregorian Easter using the anonymous computus algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    month_carry = (32 + 2 * e + 2 * i - h - k) % 7
    correction = (a + 11 * h + 22 * month_carry) // 451
    month = (h + month_carry - 7 * correction + 114) // 31
    day = (h + month_carry - 7 * correction + 114) % 31 + 1
    return date(year, month, day)


def italian_public_holidays(year: int) -> tuple[date, ...]:
    """National non-working days valid across Italy; local patron days stay tenant-managed."""
    fixed = ((1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15),
             (11, 1), (12, 8), (12, 25), (12, 26))
    easter = easter_sunday(year)
    return tuple(date(year, month, day) for month, day in fixed) + (
        easter, easter + timedelta(days=1),
    )


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _open_intervals(local_day, weekdays: tuple[int, ...], start: time, end: time, zone: ZoneInfo, closed_dates=()):
    """Return UTC-aware intervals that overlap a local date, including overnight shifts."""
    intervals = []
    closure_dates = set(closed_dates)
    if local_day.isoweekday() in weekdays and local_day not in closure_dates:
        opened = datetime.combine(local_day, start, zone)
        closed_day = local_day if start < end else local_day + timedelta(days=1)
        closed_at = datetime.combine(closed_day, end, zone)
        intervals.append((opened.astimezone(timezone.utc), closed_at.astimezone(timezone.utc)))
    previous = local_day - timedelta(days=1)
    if start >= end and previous.isoweekday() in weekdays and previous not in closure_dates:
        opened = datetime.combine(previous, start, zone)
        closed_at = datetime.combine(local_day, end, zone)
        intervals.append((opened.astimezone(timezone.utc), closed_at.astimezone(timezone.utc)))
    return intervals


def add_business_minutes(started_at: datetime, minutes: float, *, weekdays, start_time,
                         end_time, timezone_name, closed_dates=(), include_italian_holidays=False) -> datetime:
    """Add working minutes and return a naive UTC timestamp, matching database timestamps."""
    days = parse_weekdays(weekdays)
    opens, closes = parse_time(start_time), parse_time(end_time)
    if opens == closes:
        raise ValueError("L’orario di apertura e chiusura non può coincidere")
    zone = timezone_info(timezone_name)
    closures = parse_closed_dates(closed_dates)
    cursor = _utc_naive(started_at).replace(tzinfo=timezone.utc)
    remaining = max(float(minutes), 0.0) * 60
    while remaining > 0:
        local_day = cursor.astimezone(zone).date()
        calendar_closures = closures
        if include_italian_holidays:
            calendar_closures += italian_public_holidays(local_day.year)
        intervals = sorted(_open_intervals(local_day, days, opens, closes, zone, calendar_closures))
        active = next(((left, right) for left, right in intervals if right > cursor), None)
        if active is None:
            cursor = datetime.combine(local_day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
            continue
        left, right = active
        cursor = max(cursor, left)
        available = (right - cursor).total_seconds()
        if remaining <= available:
            return (cursor + timedelta(seconds=remaining)).replace(tzinfo=None)
        remaining -= available
        cursor = right
    return cursor.replace(tzinfo=None)
