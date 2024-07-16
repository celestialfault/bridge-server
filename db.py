import os
from datetime import datetime

from beanie import Document, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient


class User(Document):
    key: str
    user_id: int
    admin: bool = False
    banned: bool = False
    ban_reason: str | None = None
    muted_until: datetime | None = None
    mute_reason: str | None = None
    linked_account: str | None = None

    @property
    def is_muted(self) -> bool:
        return self.muted_until and self.muted_until >= datetime.utcnow()


async def init():
    host = os.environ.get("MONGO_HOST", "mongodb://localhost:27017")
    await init_beanie(database=AsyncIOMotorClient(host)["swsh-bridge"], document_models=[User])
