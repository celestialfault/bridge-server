from fastapi import WebSocket

__all__ = ("manager", "UserConnection")

from common import Message


class UserConnection:
    def __init__(self, user: str, ws: WebSocket, *, system: bool = False):
        self.user = user
        self.ws = ws
        self.system = system

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


manager = ConnectionManager()
