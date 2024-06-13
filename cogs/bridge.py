import asyncio
import json
import logging
import os
import re
import urllib.parse
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Mapping, cast
from uuid import uuid4

import aiohttp
import discord
import websockets
from discord import app_commands
from discord.backoff import ExponentialBackoff
from discord.ext import commands, tasks
from pydantic import ValidationError

from antispam import AntiSpam
from common import SPAM_INTERVALS, Message, lookup_username
from db import User

log = logging.getLogger("bot.bridge")
WEBHOOK_LOCK = asyncio.Lock()
DATA = Path(__file__).parent.parent / "data.json"
EMOJI = re.compile(r"<a?(:[^:]+:)\d+>")
USER_MENTION = re.compile(r"<@!?(\d+)>")
CHANNEL_MENTION = re.compile(r"<#?(\d+)>")
FORMAT_CODE = re.compile(r"§[0-9A-FK-ORZ]", re.IGNORECASE)
USERNAME_PATTERN = re.compile(r"[a-z0-9_]{3,16}", re.IGNORECASE)

# smart quotes were a mistake
# https://stackoverflow.com/a/41516221
QUOTE_SMART_UNQUOTE_QUOTES = dict([(ord(x), ord(y)) for x, y in zip("‘’´“”–", "'''\"\"-")])
ALLOWED_UNICODE = set()


def load_allowed_unicode():
    ALLOWED_UNICODE.clear()
    with open(Path(__file__).parent.parent / "allowed_unicode.txt") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            if line.startswith("#") or not line:
                continue
            ALLOWED_UNICODE.update(line)


def limit_character_set(string):
    """1.8.9 is an absolutely ancient version and has no concept of a significant amount of
    unicode characters that exist, so just strip out characters it doesn't recognize"""
    return "".join(c for c in string if 0 < ord(c) < 127 or c in ALLOWED_UNICODE)


class Bridge(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ws: websockets.WebSocketClientProtocol = ...
        self.channel = bot.get_channel(int(os.environ["BRIDGE_CHANNEL"]))
        self.sent: set[str] = set()
        self.backoff = ExponentialBackoff()
        self.backoff._max = 5
        self.antispam: Mapping[int, AntiSpam] = defaultdict(lambda: AntiSpam(SPAM_INTERVALS))
        self.soopy_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self._webhook: discord.Webhook | None = None
        self.bot.loop.create_task(self.get_webhook())

    async def cog_unload(self) -> None:
        self.ws_handler.cancel()
        await self.ws.close()
        await self.soopy_session.close()

    async def init_ws(self):
        self.ws = await websockets.connect(
            f"ws://localhost:{os.environ['BRIDGE_PORT']}/bot/{os.environ['BOT_KEY']}"
        )

    async def get_webhook(self) -> discord.Webhook:
        await self.bot.wait_until_ready()
        if self._webhook is not None:
            # Avoid locking if we don't need to
            return self._webhook

        async with WEBHOOK_LOCK:
            if self._webhook is not None:
                # Handle the case where multiple calls were made to this within a short time frame,
                # and we did end up locking
                return self._webhook

            channel = self.bot.get_channel(int(os.environ["BRIDGE_CHANNEL"]))
            if channel is None:
                raise RuntimeError("cant find bridge channel")

            webhook_id: int | None = None
            if DATA.exists():
                with open(DATA) as f:
                    webhook_id = cast(dict, json.load(f)).get("webhook", None)

            if webhook_id is not None:
                try:
                    self._webhook = await self.bot.fetch_webhook(webhook_id)
                    log.info("Using existing webhook with id %s", self._webhook.id)
                    return self._webhook
                except discord.NotFound:
                    log.warning("Can't find webhook, creating new one")

            self._webhook = webhook = await channel.create_webhook(name="Bridge")
            log.info("Created webhook with id %s", webhook.id)
            with open(DATA, mode="w") as f:
                json.dump({"webhook": webhook.id}, f)
            return webhook

    async def sub_mentions(self, message: str) -> str:
        mentions = [*USER_MENTION.finditer(message)]
        user_ids = {int(x.group(1)) for x in mentions}
        linked_users = (
            {
                x.user_id: x.linked_account
                async for x in User.find_many({"user_id": {"$in": [*user_ids]}})
                if x and x.linked_account
            }
            if user_ids
            else {}
        )

        for mention, uid in {str(x.group(0)): int(x.group(1)) for x in mentions}.items():
            if uid in linked_users:
                message = message.replace(mention, f"@{linked_users[uid]}")
            else:
                user = self.channel.guild.get_member(uid)
                if user:
                    message = message.replace(
                        mention, f"@{limit_character_set(user.display_name) or str(user)}"
                    )
                else:
                    message = message.replace(mention, "@unknown-user")

        for mention in CHANNEL_MENTION.finditer(message):
            channel_id = int(mention.group(1))
            channel = self.channel.guild.get_channel(channel_id)
            if channel:
                message = message.replace(mention.group(0), f"#{limit_character_set(str(channel))}")
            else:
                message = message.replace(mention.group(0), "#unknown-channel")

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

        antispam = self.antispam[message.author.id]
        if antispam.spammy:
            await message.reply("Slow down there!", mention_author=True, delete_after=3)
            if message.channel.permissions_for(message.guild.me).manage_messages:
                await message.delete(delay=0.5)
            return

        content = message.content.replace("\n", " ")
        content = content.translate(QUOTE_SMART_UNQUOTE_QUOTES)
        content = EMOJI.sub(r"\1", content)
        content = await self.sub_mentions(content)
        # 1.8.9 is 10 fucking years old and has no concept of any non-ASCII characters in its
        # default font rendering, so just enforce ASCII to dodge the rendering issues entirely
        content = limit_character_set(content)

        if not content:
            return
        elif len(content) > 256:
            await message.reply(
                "Message was truncated to be under 256 characters long",
                allowed_mentions=discord.AllowedMentions.none(),
                delete_after=10,
            )
            content = content[:256]

        author = (
            (user and user.linked_account)
            or limit_character_set(message.author.display_name)
            or str(message.author)
        )
        replying_to = message.reference.cached_message if message.reference else None
        # :ohno:
        if replying_to:
            author += ", replying to "
            reply_author = replying_to.author
            if (
                reply_author.id == self.bot.user.id
                and replying_to.content
                and replying_to.content.startswith("**")
            ):
                author += replying_to.content.split("**")[1]
            elif reply_author.discriminator == "0000":
                author += reply_author.display_name
            else:
                try:
                    referenced_user = (
                        await User.find_one({"user_id": reply_author.id})
                        if not reply_author.bot
                        else None
                    )
                except ValidationError:
                    referenced_user = None
                author += (
                    (referenced_user and referenced_user.linked_account)
                    or limit_character_set(reply_author.display_name)
                    or str(reply_author)
                )

        nonce = str(uuid4())
        antispam.stamp()
        self.sent.add(nonce)

        data = {
            "author": f"[DISCORD] {author}",
            "message": content,
            "nonce": nonce,
        }
        if message.flags.suppress_notifications:
            data["pings"] = False

        await self.ws.send(json.dumps(data))
        if self._is_possibly_soopy(content):
            if user and user.linked_account:
                # noinspection PyAsyncCall
                self.bot.loop.create_task(
                    self.soopy_command(message=content, author=user.linked_account)
                )
            else:
                await message.reply(
                    "Use `/link` before using Soopy commands in Discord!",
                    delete_after=10,
                    mention_author=False,
                )

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
                # this could hold up the message queue once per person for ~4 seconds every
                # 6 hours or so; might be worth looking into shoving into a task or something
                # in the future, but for now its probably fine.
                try:
                    await self._send_to_discord(data, message)
                except discord.HTTPException as e:
                    log.error("Failed to send message", exc_info=e)
        except websockets.ConnectionClosedError:
            delay = self.backoff.delay()
            log.warning(f"Websocket connection closed, waiting {delay} to reconnect")
            await asyncio.sleep(delay)
            await self.init_ws()

    async def _send_to_discord(self, data: Message, message: str):
        if data.get("system", False):
            await self.channel.send(
                embed=discord.Embed(description=message, colour=discord.Colour.orange())
            )
            return

        avatar: str | None = None
        if USERNAME_PATTERN.fullmatch(data["author"]):
            user_data = await lookup_username(data["author"], timeout=4)
            if user_data:
                # discord has some incredibly wacky caching which makes virtually no sense in what
                # it caches or for how long, so just opt to add a query string parameter in an
                # attempt to forcefully make discord disregard whatever cache it might have once
                # per day.
                discord_cache_bust = date.today().strftime("%y%m%d")
                avatar = f"https://visage.surgeplay.com/face/256/{user_data['id']}?_={discord_cache_bust}"

        if message.startswith(" "):
            # preserve spaces at the beginning of a message by adding a zwj to prevent discord
            # from "helpfully" trimming the message
            message = f"\N{ZERO WIDTH JOINER}{message}"

        webhook = await self.get_webhook()
        await webhook.send(
            content=message,
            username=data["author"],
            avatar_url=avatar,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        if self._is_possibly_soopy(message):
            # shut up pycharm
            # noinspection PyAsyncCall
            self.bot.loop.create_task(self.soopy_command(message, data["author"]))

    async def _send_system(self, message: str):
        await self.ws.send(
            json.dumps(
                {
                    "system": True,
                    "author": "Bot",
                    "message": message,
                    # note that we don't do anything with the nonce here, unlike with other messages
                    # we send - this is on purpose, as we want this to be echoed back for us so we
                    # don't have to handle sending this ourselves
                    "nonce": str(uuid4()),
                }
            )
        )

    @staticmethod
    def _is_possibly_soopy(message: str):
        if not message.startswith("-") or message.startswith("- "):
            return False

        try:
            # ignore messages which are simply negative numbers
            float(message[1:].split(" ")[0])
        except ValueError:
            return True
        else:
            return False

    async def soopy_command(self, message: str, author: str):
        if not self._is_possibly_soopy(message):
            return

        # this can be safely echoed back as this method is only ever called once we've done some
        # basic sanitization on the message
        await self._send_system(f"§7[SOOPY V2] {message}")
        try:
            command = urllib.parse.quote_plus(message[1:])
            uri = f"https://soopy.dev/api/guildBot/runCommand?user={author}&cmd={command}"
            async with self.soopy_session.get(uri) as resp:
                data = await resp.json()
        except asyncio.TimeoutError:
            await self._send_system("§7[SOOPY V2] Timed out waiting for a response")
            return
        except aiohttp.ClientError as e:
            log.warning("Soopy guild bot API returned an error", exc_info=e)
            data = None

        if not data:
            await self._send_system("§7[SOOPY V2] An error occurred while running the command")
            return
        if not data.get("success") or "raw" not in data:
            cause = data.get("cause", "An error occurred while running the command")
            await self._send_system(f"§7[SOOPY V2] {cause}")
            return

        await self._send_system(f"§7[SOOPY V2] {data['raw']}")

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

    @commands.hybrid_command()
    @app_commands.describe(username="Your IGN")
    @app_commands.guilds(discord.Object(id=int(os.environ["BRIDGE_GUILD"])))
    async def link(self, ctx: commands.Context, username: str):
        """Link your Minecraft account"""
        if not USERNAME_PATTERN.fullmatch(username):
            await ctx.send("That isn't a valid username!", ephemeral=True)
            return
        user = await User.find_one({"user_id": ctx.author.id})
        if not user:
            user = User(user_id=ctx.author.id, key=str(uuid4()))
            # noinspection PyArgumentList
            await user.insert()
        if user.banned:
            await ctx.send("You are currently banned from using the bridge!", ephemeral=True)
            return

        await ctx.defer()
        data = await lookup_username(username)
        if not data:
            await ctx.send("That username doesn't exist!")
            return
        await user.set({"linked_account": data["username"]})
        await ctx.send(f"Updated your IGN to `{user.linked_account}`")


async def setup(bot: commands.Bot):
    # yeah this is a blocking method in an async method but whatever, its a small text file,
    # it shouldn't be that huge an issue for how often this is called.
    load_allowed_unicode()
    cog = Bridge(bot)
    await cog.init_ws()
    cog.ws_handler.start()
    await bot.add_cog(cog)
