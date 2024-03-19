from typing import TypedDict

from fastapi import WebSocket

__all__ = ("Message", "manager")


class Message(TypedDict):
    author: str
    message: str


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.remove(ws)

    async def broadcast(self, message: Message):
        for connection in self.active_connections:
            await self.send_message_to(message, connection)

    @staticmethod
    async def send_message_to(message: Message, ws: WebSocket):
        await ws.send_json(message)


manager = ConnectionManager()
