import os
from contextlib import asynccontextmanager
from datetime import datetime
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
from fastapi.responses import JSONResponse

from common import MuteRequest, ModRequest, delta_to_str
from connections import manager, UserConnection
from db import User, init


@asynccontextmanager
async def before_startup(_):
    load_dotenv()
    os.environ.pop("DISCORD_TOKEN")
    await init()
    yield


app = FastAPI(lifespan=before_startup)


def uuid():
    return str(uuid4())


async def get_user_from_key(key: str) -> User | None:
    return await User.find_one({"key": key})


def is_valid_bot_key(key: str) -> bool:
    return key is not None and key == os.environ["BOT_KEY"]


@app.post("/ban")
async def ban(request: ModRequest, bot_key: Annotated[str, Header()]):
    if not is_valid_bot_key(bot_key):
        return JSONResponse(
            status_code=403, content={"success": False, "reason": "Invalid bot key"}
        )

    target = await User.find_one({"user_id": request.id})
    if not target:
        target = User(user_id=request.id, key=uuid())
    if target and target.admin:
        return JSONResponse(
            status_code=400,
            content={"success": False, "reason": "Cannot ban an admin"},
        )
    await target.set({"banned": True, "ban_reason": request.reason})

    for connection in manager.all_from(target):
        await connection.send_system(
            f"§cYou have been banned:§r {target.ban_reason or 'No reason specified'}"
        )
        await connection.disconnect(reason="You have been banned", code=1008)

    return {"success": True}


@app.post("/unban")
async def unban(request: ModRequest, bot_key: Annotated[str, Header()]):
    if not is_valid_bot_key(bot_key):
        return JSONResponse(
            status_code=403, content={"success": False, "reason": "Invalid bot key"}
        )

    target = await User.find_one({"user_id": request.id})
    if not target or not target.banned:
        return {"success": False, "reason": "User is not banned"}
    await target.set({"banned": False, "ban_reason": None})
    return {"success": True}


@app.post("/mute")
async def mute(request: MuteRequest, bot_key: Annotated[str, Header()]):
    if not is_valid_bot_key(bot_key):
        return JSONResponse(
            status_code=403, content={"success": False, "reason": "Invalid bot key"}
        )

    target = await User.find_one({"user_id": request.id})
    if not target:
        target = User(user_id=request.id, key=uuid())
    if target.admin and request.until:
        return JSONResponse(
            status_code=400,
            content={"success": False, "reason": "Cannot mute an admin"},
        )
    if target.banned:
        return JSONResponse(
            status_code=400,
            content={"success": False, "reason": "User is currently banned"},
        )
    if not target.is_muted() and not request.until:
        return JSONResponse(
            status_code=400,
            content={"success": False, "reason": "User is not currently muted"},
        )
    await target.set({"muted_until": request.until, "mute_reason": request.reason})

    for connection in manager.all_from(target):
        connection.user_data = target
        if target.is_muted():
            await _send_muted(connection, tense="have been")
        else:
            await connection.send_system("§bYou have been unmuted.")

    return {"success": True}


@app.get("/online")
async def online(bot_key: Annotated[str, Header()]):
    if not is_valid_bot_key(bot_key):
        return JSONResponse(
            status_code=403, content={"success": False, "reason": "Invalid bot key"}
        )

    return {x.user for x in manager.active_connections if not x.system}


@app.websocket("/bot/{bot_key}")
async def bot_websocket(ws: WebSocket, bot_key: str):
    if not is_valid_bot_key(bot_key):
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
    if user.banned:
        ban_reason = user.ban_reason if user.ban_reason else "No reason specified"
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason=f"You are banned: {ban_reason}"
        )

    connection = UserConnection(username, ws, user_data=user)
    await manager.connect(connection)
    try:
        while True:
            if api_version == 0:
                message = await ws.receive_text()
                if connection.is_muted():
                    await _send_muted(connection)
                    continue
                await _broadcast(username, message)
            elif api_version == 1:
                data = await ws.receive_json()
                type = data.get("type")
                if type == "send":
                    if connection.is_muted():
                        await _send_muted(connection)
                        continue
                    await _broadcast(
                        username, str(data["data"]), nonce=str(data.get("nonce"))
                    )
                elif type == "request_online":
                    await _send_online(connection)
    except WebSocketDisconnect:
        manager.disconnect(connection)


async def _send_muted(connection: UserConnection, tense: str = "are"):
    duration = delta_to_str(connection.user_data.muted_until - datetime.utcnow())
    reason = connection.user_data.mute_reason or "No reason specified"

    await connection.send_system(f"§cYou {tense} muted for {duration}:§r {reason}")


async def _send_online(connection: UserConnection, *, color: bool = True):
    online = "§aOnline:§r " if color else "Online: "
    connected = {x.user for x in manager.active_connections if not x.system}
    await connection.send_system(online + ", ".join(connected))


async def _broadcast(user: str, message: str, *, nonce: str = None):
    await manager.broadcast(
        {"author": user, "message": message, "nonce": nonce or uuid()}
    )
