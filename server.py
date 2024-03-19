from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, WebSocketException, status

from connections import manager
from db import User, init


@asynccontextmanager
async def before_startup(_):
    await init()
    yield


app = FastAPI(lifespan=before_startup)


async def get_user_from_key(key: str) -> User | None:
    return await User.find_one({"key": key})


@app.websocket("/ws/{username}/{key}")
async def websocket(ws: WebSocket, username: str, key: str):
    user = await get_user_from_key(key)
    if not user:
        print("Blocking attempted connection with invalid key")
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    print(f"Connection opened from {username}")

    await manager.connect(ws)
    try:
        while True:
            message = await ws.receive_text()
            await manager.broadcast({"author": username, "message": message})
    except WebSocketDisconnect:
        manager.disconnect(ws)
