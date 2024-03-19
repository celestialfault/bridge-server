import json
import os
from typing import cast
from uuid import uuid4

import discord
import websockets
from discord.ext import commands
from discord.ext import tasks

from common import Message


class Bridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ws: websockets.WebSocketClientProtocol = ...
        self.channel = bot.get_channel(int(os.environ["BRIDGE_CHANNEL"]))
        print(os.environ["BRIDGE_CHANNEL"], self.channel)
        self.sent: set[str] = set()

    async def cog_unload(self) -> None:
        self.ws_handler.cancel()
        await self.ws.close()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.author.bot
            or message.content.startswith(self.bot.user.mention)
            or message.channel.id != self.channel.id
        ):
            return

        nonce = uuid4()
        self.sent.add(str(nonce))
        await self.ws.send(
            json.dumps(
                {
                    "author": message.author.name,
                    "message": message.content,
                    "nonce": str(nonce),
                }
            )
        )

    @tasks.loop()
    async def ws_handler(self):
        async for message in self.ws:
            data: Message = cast(Message, json.loads(message))

            if data["nonce"] in self.sent:
                self.sent.discard(data["nonce"])
                continue

            await self.channel.send(f"**{data['author']}**: {data['message']}")


async def setup(bot: commands.Bot):
    cog = Bridge(bot)
    cog.ws = await websockets.connect(
        f"ws://localhost:{os.environ['BRIDGE_PORT']}/bot/{os.environ['BOT_KEY']}"
    )
    cog.ws_handler.start()
    await bot.add_cog(cog)
