from typing import Iterator
from uuid import uuid4

from fastapi import WebSocket

__all__ = ("manager", "UserConnection")

from common import Message
from db import User


class UserConnection:
    def __init__(
        self, user: str, ws: WebSocket, *, system: bool = False, user_data: User = None
    ):
        self.user = user
        self.ws = ws
        self.system = system
        self.user_data = user_data

    def is_muted(self) -> bool:
        return self.user_data and self.user_data.is_muted()

    async def disconnect(self, code: int = 1000, reason: str | None = None):
        await self.ws.close(code=code, reason=reason)

    async def send_system(self, message: str):
        await self.send_json(
            {"system": True, "author": "", "message": message, "nonce": str(uuid4())}
        )

    async def send_json(self, data: dict):
        await self.ws.send_json(data)


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
