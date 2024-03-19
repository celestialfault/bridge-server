import os
from contextlib import asynccontextmanager
from uuid import uuid4

from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, WebSocketException, status

from connections import manager
from db import User, init


@asynccontextmanager
async def before_startup(_):
    load_dotenv()
    if "DISCORD_TOKEN" in os.environ:
        del os.environ["DISCORD_TOKEN"]
    await init()
    yield


app = FastAPI(lifespan=before_startup)


async def get_user_from_key(key: str) -> User | None:
    return await User.find_one({"key": key})


@app.websocket("/bot/{bot_key}")
async def bot_websocket(ws: WebSocket, bot_key: str):
    if bot_key != os.environ["BOT_KEY"]:
        print("Blocking attempted bot connection with invalid key")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await manager.connect(ws)
    try:
        while True:
            message = await ws.receive_json()
            await manager.broadcast(message)
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.websocket("/ws/{username}/{key}")
async def websocket(ws: WebSocket, username: str, key: str):
    user = await get_user_from_key(key)
    if not user:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    await manager.connect(ws)
    try:
        while True:
            message = await ws.receive_text()
            await manager.broadcast({"author": username, "message": message, "nonce": str(uuid4())})
    except WebSocketDisconnect:
        manager.disconnect(ws)
