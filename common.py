from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TypedDict, MutableMapping

import aiohttp
from pydantic import BaseModel

__all__ = (
    "delta_to_str",
    "lookup_username",
    "Message",
    "ModRequest",
    "MuteRequest",
    "PlayerData",
    "SPAM_INTERVALS",
)
log = logging.getLogger("common")
TIME_UNITS = ((60 * 60 * 24, "d"), (60 * 60, "h"), (60, "m"), (1, "s"))
SPAM_INTERVALS: list[tuple[timedelta, int]] = [
    (timedelta(seconds=4), 5),
    (timedelta(seconds=10), 10),
    (timedelta(seconds=60), 40),
]
USERNAME_CACHE: MutableMapping[str, tuple[PlayerData | None, datetime]] = {}


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


# this isn't the entire response payload from playerdb, but it's all that we care about here.
class PlayerData(TypedDict):
    username: str
    id: str


async def lookup_username(username_or_uuid: str, *, timeout: int = 10) -> PlayerData | None:
    username_or_uuid = username_or_uuid.casefold()
    if username_or_uuid in USERNAME_CACHE and (
        USERNAME_CACHE[username_or_uuid][1] < datetime.utcnow() + timedelta(hours=6)
    ):
        return USERNAME_CACHE[username_or_uuid][0]

    try:
        uri = f"https://playerdb.co/api/player/minecraft/{username_or_uuid}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(uri) as resp:
                resp.raise_for_status()
                data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        log.warning("Failed to lookup username %s", username_or_uuid, exc_info=e)

    if not data or not data.get("success") or "data" not in data:
        USERNAME_CACHE[username_or_uuid] = (None, datetime.utcnow())
    else:
        USERNAME_CACHE[username_or_uuid] = (data["data"]["player"], datetime.utcnow())

    return USERNAME_CACHE[username_or_uuid][0]
