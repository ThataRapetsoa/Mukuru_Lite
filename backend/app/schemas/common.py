from datetime import datetime, timezone
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_datetime(value: object) -> datetime:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("datetime must be an ISO-8601 string")
    return normalize_utc(parsed)


UtcTimestamp = Annotated[
    datetime,
    BeforeValidator(parse_datetime),
    PlainSerializer(
        lambda value: normalize_utc(value).isoformat().replace("+00:00", "Z"),
        return_type=str,
        when_used="json",
    ),
]