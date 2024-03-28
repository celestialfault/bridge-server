import asyncio.subprocess
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, cast
from uuid import uuid4

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from db import User
from time_converter import TimeDelta

FORMAT_CODE = re.compile(r"&([0-9A-FK-ORZ])", re.IGNORECASE)


def bridge_admin():
    async def predicate(ctx: commands.Context):
        user = await User.find_one({"user_id": ctx.author.id})
        if not user or not user.admin:
            raise commands.CheckFailure()
        return True

    return commands.check(predicate)


class Mod(commands.Cog):
    @staticmethod
    async def _post(endpoint: str, data: dict) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"http://localhost:{os.environ['BRIDGE_PORT']}/{endpoint}",
                json=data,
                headers={"Bot-Key": os.environ["BOT_KEY"]},
            ) as request:
                return await request.json()

    @commands.hybrid_group()
    @app_commands.guilds(discord.Object(id=int(os.environ["BRIDGE_GUILD"])))
    @bridge_admin()
    async def bridge(self, ctx: commands.Context):
        """Bridge moderation commands"""

    @bridge.command()
    @bridge_admin()
    @commands.check(lambda ctx: (Path(os.getcwd()) / "restart.sh").exists())
    async def restart(self, ctx: commands.Context):
        """Restart the bridge server"""
        await ctx.send("Restarting...")
        p = await asyncio.subprocess.create_subprocess_exec(
            "sh restart.sh", stdout=sys.stdout, stderr=sys.stderr
        )
        await p.wait()
        await ctx.bot.close()

    @bridge.command()
    @app_commands.describe(
        message="The message to announce; color codes (e.g. &a) are supported"
    )
    @bridge_admin()
    async def announce(self, ctx: commands.Context, *, message: str):
        """Send a system message through the bot"""
        from cogs.bridge import Bridge

        bridge_cog = cast(Bridge, ctx.bot.get_cog("Bridge"))
        message = FORMAT_CODE.sub(r"§\1", message)
        if "§" not in message:
            message = f"§6{message}"
        await bridge_cog.ws.send(
            {
                "author": str(ctx.author),
                "message": message,
                "nonce": str(uuid4()),
                "system": True,
            }
        )
        await ctx.send("Announcement sent!")

    # noinspection PyTypeHints
    @bridge.command()
    @app_commands.describe(
        user="The Discord user to mute",
        duration="How long to mute for, e.g. '1d'",
        reason="The reason to display when the muted user attempts to speak",
    )
    @bridge_admin()
    async def mute(
        self,
        ctx: commands.Context,
        user: discord.User,
        duration: Annotated[timedelta, TimeDelta(min="1s")],
        *,
        reason: str = None,
    ):
        """Temporarily mute a user"""
        await ctx.defer()
        until: datetime = datetime.utcnow() + duration
        response = await self._post(
            "mute", {"id": user.id, "until": until.isoformat(), "reason": reason}
        )
        if response.get("success"):
            await ctx.send(
                f"\N{WHITE HEAVY CHECK MARK} {user.mention} is now muted until {discord.utils.format_dt(until)}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send(
                f"\N{WARNING SIGN}\N{VARIATION SELECTOR-16} {response.get('reason')}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @bridge.command()
    @app_commands.describe(user="The Discord user to unmute")
    @bridge_admin()
    async def unmute(self, ctx: commands.Context, user: discord.User):
        """Unmute a user"""
        await ctx.defer()
        response = await self._post("mute", {"id": user.id, "until": None})
        if response.get("success"):
            await ctx.send(
                f"\N{WHITE HEAVY CHECK MARK} {user.mention} has been unmuted.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send(
                f"\N{WARNING SIGN}\N{VARIATION SELECTOR-16} {response.get('reason')}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @bridge.command()
    @app_commands.describe(
        user="The Discord user to ban from the bridge", reason="The reason for this ban"
    )
    @bridge_admin()
    async def ban(
        self, ctx: commands.Context, user: discord.User, *, reason: str = None
    ):
        """Ban a user from using the bridge"""
        await ctx.defer()
        response = await self._post("ban", {"id": user.id, "reason": reason})
        if response.get("success"):
            await ctx.send(
                f"\N{WHITE HEAVY CHECK MARK} {user.mention} is now banned from using the bridge.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send(
                f"\N{WARNING SIGN}\N{VARIATION SELECTOR-16} {response.get('reason')}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @bridge.command()
    @app_commands.describe(user="The Discord user to unban from the bridge")
    @bridge_admin()
    async def unban(self, ctx: commands.Context, user: discord.User):
        """Unban a previously bridge-banned user"""
        await ctx.defer()
        response = await self._post("unban", {"id": user.id})
        if response.get("success"):
            await ctx.send(
                f"\N{WHITE HEAVY CHECK MARK} {user.mention} has been unbanned.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await ctx.send(
                f"\N{WARNING SIGN}\N{VARIATION SELECTOR-16} {response.get('reason')}",
                allowed_mentions=discord.AllowedMentions.none(),
            )


async def setup(bot):
    await bot.add_cog(Mod())
