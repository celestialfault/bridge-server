import asyncio
import json
import os
import re
from typing import cast
from uuid import uuid4

import aiohttp
import discord
import websockets
from discord import app_commands
from discord.backoff import ExponentialBackoff
from discord.ext import commands, tasks

from common import Message
from db import User

EMOJI = re.compile(r"<a?(:[^:]+:)\d+>")
USER_MENTION = re.compile(r"<@!?(\d+)>")
CHANNEL_MENTION = re.compile(r"<#?(\d+)>")
FORMAT_CODE = re.compile(r"§[0-9A-FK-ORZ]", re.IGNORECASE)


def strip_non_ascii(string):
    return "".join(c for c in string if 0 < ord(c) < 127)


class Bridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ws: websockets.WebSocketClientProtocol = ...
        self.channel = bot.get_channel(int(os.environ["BRIDGE_CHANNEL"]))
        self.sent: set[str] = set()
        self.backoff = ExponentialBackoff()
        self.backoff._max = 5

    async def cog_unload(self) -> None:
        self.ws_handler.cancel()
        await self.ws.close()

    async def init_ws(self):
        self.ws = await websockets.connect(
            f"ws://localhost:{os.environ['BRIDGE_PORT']}/bot/{os.environ['BOT_KEY']}"
        )

    def sub_mentions(self, message: str) -> str:
        for mention in USER_MENTION.finditer(message):
            user_id = int(mention.group(1))
            user = self.channel.guild.get_member(user_id)
            if user:
                message = message.replace(mention.group(0), f"@{user.display_name}")

        for mention in CHANNEL_MENTION.finditer(message):
            channel_id = int(mention.group(1))
            channel = self.channel.guild.get_channel(channel_id)
            if channel:
                message = message.replace(mention.group(0), f"#{channel}")

        return message

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.author.bot
            or message.content.startswith(self.bot.user.mention)
            or message.channel.id != self.channel.id
            or not message.content
        ):
            return

        user: User | None = await User.find_one({"user_id": message.author.id})
        if user and (user.is_muted or user.banned):
            if message.channel.permissions_for(message.guild.me).manage_messages:
                await message.delete()

            if user.banned:
                from cogs.mod import Mod

                await Mod.remove_permissions(message.channel, message.author)
            return

        content = message.content.replace("\n", " ")
        content = EMOJI.sub(r"\1", content)
        content = self.sub_mentions(content)
        # 1.8.9 is 10 fucking years old and has no concept of any non-ASCII characters in its
        # default font rendering, so just enforce ASCII to dodge the rendering issues entirely
        content = strip_non_ascii(content)

        if not content:
            return
        elif len(content) > 256:
            await message.reply(
                "Message was truncated to be under 256 characters long",
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=5,
            )
            content = content[:256]

        author = strip_non_ascii(message.author.display_name) or str(message.author)
        replying_to = message.reference.cached_message if message.reference else None
        if replying_to and (replying_to.author.id != self.bot.user.id or replying_to.content):
            author += ", replying to "
            reply_author = message.reference.cached_message.author
            if reply_author.id == self.bot.user.id:
                author += message.reference.cached_message.content.split("**")[1]
            else:
                author += strip_non_ascii(reply_author.display_name) or str(reply_author)

        nonce = uuid4()
        self.sent.add(str(nonce))

        data = {
            "author": f"[DISCORD] {author}",
            "message": content,
            "nonce": str(nonce),
        }
        if message.flags.suppress_notifications:
            data["pings"] = False

        await self.ws.send(json.dumps(data))

    @tasks.loop()
    async def ws_handler(self):
        try:
            async for message in self.ws:
                data: Message = cast(Message, json.loads(message))

                if data["nonce"] in self.sent:
                    self.sent.discard(data["nonce"])
                    continue

                message = data["message"]
                message = FORMAT_CODE.sub("", message)

                if data.get("system", False):
                    await self.channel.send(
                        embed=discord.Embed(description=message, colour=discord.Colour.orange())
                    )
                else:
                    await self.channel.send(
                        f"**{data['author']}**: {message}",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
        except websockets.ConnectionClosedError:
            delay = self.backoff.delay()
            print(f"Websocket connection closed, waiting {delay} to reconnect")
            await asyncio.sleep(delay)
            await self.init_ws()

    @commands.hybrid_command()
    @app_commands.guilds(discord.Object(id=int(os.environ["BRIDGE_GUILD"])))
    async def online(self, ctx: commands.Context):
        """List all players currently connected to the in-game bridge"""
        if ctx.interaction:
            await cast(discord.InteractionResponse, ctx.interaction.response).defer(
                ephemeral=True, thinking=True
            )
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://localhost:{os.environ['BRIDGE_PORT']}/online",
                headers={"Bot-Key": os.environ["BOT_KEY"]},
            ) as o:
                users: dict[str, int] = await o.json()

        if not users:
            await ctx.send("There is nobody online.")
            return

        user = await User.find_one({"user_id": ctx.author.id})
        if user and user.admin and ctx.interaction:
            online = "\n".join([f"- **{user}**: <@{id}>" for user, id in users.items()])
            await ctx.send(
                f"**Users currently online:**\n\n{online}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send(f"**Users currently online:** {', '.join(users.keys())}")


async def setup(bot: commands.Bot):
    cog = Bridge(bot)
    await cog.init_ws()
    cog.ws_handler.start()
    await bot.add_cog(cog)
