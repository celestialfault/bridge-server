import asyncio
import logging
from datetime import datetime
from typing import Iterator
from uuid import uuid4

from fastapi import WebSocket

from antispam import AntiSpam
from common import SPAM_INTERVALS, Message, delta_to_str, get_persistent_data
from db import User

__all__ = ("manager", "UserConnection")
log = logging.getLogger("connections")


class UserConnection:
    def __init__(self, user: str, ws: WebSocket, *, system: bool = False, user_data: User = None):
        self.user = user
        self.ws = ws
        self.system = system
        self.user_data = user_data
        self.antispam = AntiSpam(SPAM_INTERVALS)
        self.send_queue: asyncio.Queue[Message] = asyncio.Queue()
        # you are wrong pycharm, now be quiet
        # noinspection PyUnreachableCode
        self.queue_dispatcher = asyncio.get_event_loop().create_task(self._dispatch_queue())

    async def _dispatch_queue(self) -> None:
        while True:
            try:
                await self.send_json(await self.send_queue.get())
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.error("Failed to send queued message", exc_info=e)

    def is_muted(self) -> bool:
        return self.user_data and self.user_data.is_muted

    async def disconnect(self, code: int = 1000, reason: str | None = None):
        await self.ws.close(code=code, reason=reason)

    async def send_system(self, message: str, *, author: str = "System"):
        await self.send_json(
            {"system": True, "author": author, "message": message, "nonce": str(uuid4())}
        )

    async def send_json(self, data: dict):
        await self.ws.send_json(data)

    # noinspection PyShadowingBuiltins
    async def handle_ws_request(self, type: str, data: dict):
        if type == "send":
            message: str = data["data"]
            if not message.replace(" ", ""):
                return

            if not get_persistent_data().get("accept_messages", True) and not self.user_data.admin:
                await self.send_system(f"§cThe bridge is not currently accepting messages")
                return

            if self.is_muted():
                duration = delta_to_str(self.user_data.muted_until - datetime.utcnow())
                reason = self.user_data.mute_reason or "No reason specified"
                await self.send_system(f"§cYou are muted for {duration}:§r {reason}")
                return

            if self.antispam.spammy:
                await self.send_system(f"§cSlow down there!", author="System")
                return
            self.antispam.stamp()

            await self._broadcast(self.user, str(data["data"]), nonce=data.get("nonce"))

        elif type == "request_online":
            connected = {x.user for x in manager.active_connections if not x.system}
            await self.send_system("§aOnline:§r " + ", ".join(connected))

    @staticmethod
    async def _broadcast(user: str, message: str, *, nonce: str = None):
        # noinspection PyArgumentList
        await manager.broadcast(Message(author=user, message=message, nonce=str(nonce or uuid4())))


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[UserConnection] = []

    async def connect(self, user: UserConnection):
        await user.ws.accept()
        self.active_connections.append(user)

    def disconnect(self, user: UserConnection):
        self.active_connections.remove(user)
        user.queue_dispatcher.cancel()

    async def broadcast(self, message: Message):
        for user in self.active_connections:
            user.send_queue.put_nowait(message)

    def all_from(self, user: User) -> Iterator[UserConnection]:
        for connection in self.active_connections:
            if connection.user_data and connection.user_data.id == user.id:
                yield connection


manager = ConnectionManager()
