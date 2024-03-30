from datetime import datetime
from typing import Iterator, cast
from uuid import uuid4

from fastapi import WebSocket

from antispam import AntiSpam
from common import Message, delta_to_str, SPAM_INTERVALS
from db import User

__all__ = ("manager", "UserConnection")


class UserConnection:
    def __init__(self, user: str, ws: WebSocket, *, system: bool = False, user_data: User = None):
        self.user = user
        self.ws = ws
        self.system = system
        self.user_data = user_data
        self.antispam = AntiSpam(SPAM_INTERVALS)

    def is_muted(self) -> bool:
        return self.user_data and self.user_data.is_muted

    async def disconnect(self, code: int = 1000, reason: str | None = None):
        await self.ws.close(code=code, reason=reason)

    async def send_system(self, message: str, *, author: str = ""):
        await self.send_json(
            {"system": True, "author": author, "message": message, "nonce": str(uuid4())}
        )

    async def send_json(self, data: dict):
        await self.ws.send_json(data)

    # noinspection PyShadowingBuiltins
    async def handle_ws_request(self, type: str, data: dict):
        if type == "send":
            if self.is_muted():
                duration = delta_to_str(self.user_data.muted_until - datetime.utcnow())
                reason = self.user_data.mute_reason or "No reason specified"
                await self.send_system(f"§cYou are muted for {duration}:§r {reason}")
                return

            if self.antispam.spammy:
                await self.send_system(f"§cSlow down there!", author="System")
                return
            self.antispam.stamp()

            await self._broadcast(self.user, str(data["data"]), nonce=str(data.get("nonce")))

        elif type == "request_online":
            connected = {x.user for x in manager.active_connections if not x.system}
            await self.send_system("§aOnline:§r " + ", ".join(connected))

    @staticmethod
    async def _broadcast(user: str, message: str, *, nonce: str = None):
        # noinspection PyTypeChecker
        await manager.broadcast(
            {
                "author": user,
                "message": message,
                # shut up pycharm
                "nonce": cast(str, nonce or str(uuid4())),
            }
        )


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[UserConnection] = []

    async def connect(self, user: UserConnection):
        await user.ws.accept()
        self.active_connections.append(user)

    def disconnect(self, user: UserConnection):
        self.active_connections.remove(user)

    async def broadcast(self, message: Message):
        for user in self.active_connections:
            await user.send_json(message)

    def all_from(self, user: User) -> Iterator[UserConnection]:
        for connection in self.active_connections:
            if connection.user_data and connection.user_data.id == user.id:
                yield connection


manager = ConnectionManager()
