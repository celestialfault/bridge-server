import os
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import uuid4

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
    Header,
)
from fastapi.responses import PlainTextResponse

from connections import manager, UserConnection
from db import User, init


@asynccontextmanager
async def before_startup(_):
    load_dotenv()
    if "DISCORD_TOKEN" in os.environ:
        del os.environ["DISCORD_TOKEN"]
    await init()
    yield


app = FastAPI(lifespan=before_startup)


def get_nonce():
    return str(uuid4())


async def get_user_from_key(key: str) -> User | None:
    return await User.find_one({"key": key})


@app.get("/online")
async def online(bot_key: Annotated[str, Header()] = None):
    if bot_key is None or bot_key != os.environ["BOT_KEY"]:
        return PlainTextResponse(status_code=403)

    return {x.user for x in manager.active_connections if not x.system}


@app.websocket("/bot/{bot_key}")
async def bot_websocket(ws: WebSocket, bot_key: str):
    if bot_key != os.environ["BOT_KEY"]:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    connection = UserConnection("", ws, system=True)
    await manager.connect(connection)
    try:
        while True:
            message = await ws.receive_json()
            await manager.broadcast(message)
    except WebSocketDisconnect:
        manager.disconnect(connection)


@app.websocket("/ws/{username}/{key}")
async def websocket(
    ws: WebSocket, username: str, key: str, api_version: Annotated[int, Header()] = 0
):
    if api_version not in (0, 1):
        raise WebSocketException(code=status.WS_1003_UNSUPPORTED_DATA)

    user = await get_user_from_key(key)
    if not user:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    connection = UserConnection(username, ws)
    await manager.connect(connection)
    try:
        while True:
            if api_version == 0:
                message = await ws.receive_text()
                await _broadcast(username, message)
            elif api_version == 1:
                data = await ws.receive_json()
                type = data.get("type")
                if type == "send":
                    await _broadcast(username, str(data["data"]), nonce=str(data.get("nonce")))
                elif type == "request_online":
                    await _send_online(ws)
    except WebSocketDisconnect:
        manager.disconnect(connection)


async def _send_online(ws: WebSocket, *, color: bool = True):
    online = "§aOnline:§r " if color else "Online: "
    connected = {x.user for x in manager.active_connections if not x.system}
    await ws.send_json(
        {
            "system": True,
            "author": "",
            "message": online + ", ".join(connected),
            "nonce": get_nonce(),
        }
    )


async def _broadcast(user: str, message: str, *, nonce: str = None):
    await manager.broadcast({"author": user, "message": message, "nonce": nonce or get_nonce()})
