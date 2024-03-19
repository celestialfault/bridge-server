import os
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands

from db import User


class Tokens(commands.Cog):
    @commands.hybrid_command()
    @app_commands.guilds(discord.Object(id=int(os.environ["BRIDGE_GUILD"])))
    async def apikey(self, ctx: commands.Context):
        """Create a new API key for use with the bridge mod"""
        await ctx.defer(ephemeral=True)
        token = uuid4()
        if not await User.find_one({"user_id": ctx.author.id}).exists():
            await User.insert_one(User(user_id=ctx.author.id, key=token))
        else:
            await User.find_one({"user_id": ctx.author.id}).update({"$set": {"key": str(token)}})
        await ctx.send(f"Created token `{token}`", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tokens())
