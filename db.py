from beanie import Document, init_beanie
from motor.motor_asyncio import AsyncIOMotorClient


class User(Document):
    key: str
    user_id: int


async def init():
    await init_beanie(
        database=AsyncIOMotorClient("mongodb://localhost:27017")["swsh-bridge"],
        document_models=[User],
    )
