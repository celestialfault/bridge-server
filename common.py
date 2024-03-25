from datetime import datetime, timedelta
from typing import TypedDict

from pydantic import BaseModel

TIME_UNITS = ((60 * 60 * 24, "d"), (60 * 60, "h"), (60, "m"), (1, "s"))
__all__ = ("delta_to_str", "Message", "ModRequest", "MuteRequest")


def delta_to_str(delta: timedelta) -> str:
    time_difference = delta.total_seconds()
    if time_difference < 0:
        return "0s"
    time_str_parts = []

    for unit_seconds, unit_name in TIME_UNITS:
        if time_difference >= unit_seconds:
            unit_value = int(time_difference // unit_seconds)
            time_str_parts.append(f"{unit_value}{unit_name}")
            time_difference %= unit_seconds

    return " ".join(time_str_parts) if time_str_parts else "0s"


class Message(TypedDict):
    system: bool  # = False
    pings: bool  # = True
    author: str
    message: str
    nonce: str


class ModRequest(BaseModel):
    id: int
    reason: str | None = None


class MuteRequest(ModRequest):
    until: datetime | None
