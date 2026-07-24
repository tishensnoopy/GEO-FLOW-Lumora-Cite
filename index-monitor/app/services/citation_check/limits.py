"""Quota-related time helpers."""

import datetime
from zoneinfo import ZoneInfo


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def beijing_day(now: datetime.datetime | None = None) -> datetime.date:
    """Return the quota day, which always resets at Beijing midnight."""
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    return now.astimezone(BEIJING_TZ).date()
