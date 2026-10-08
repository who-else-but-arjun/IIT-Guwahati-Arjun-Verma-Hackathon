"""Date and time parsing helpers used at API and connector boundaries."""

from datetime import date, datetime, time, timezone


def parse_datetime(value: datetime | str | int | float | None) -> datetime:
    if isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def parse_date(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_optional_time(value: str | None) -> datetime | date | None:
    if value is None or value == "":
        return None
    if "T" not in value and " " not in value:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Recency dates must use YYYY-MM-DD or ISO datetime format") from exc
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Recency dates must use YYYY-MM-DD or ISO datetime format") from exc


def parse_optional_float(value: str | None, name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def utc_date_boundary(value: datetime | date, *, end_of_date: bool) -> datetime:
    if isinstance(value, datetime):
        bound = value
    elif end_of_date:
        bound = datetime.combine(value, time.max)
    else:
        bound = datetime.combine(value, time.min)
    if bound.tzinfo is None:
        bound = bound.replace(tzinfo=timezone.utc)
    return bound.astimezone(timezone.utc)
