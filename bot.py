import logging
import os
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Bot, when_mentioned
from dotenv import load_dotenv

from db import init

load_dotenv()
intents = discord.Intents(messages=True, message_content=True, members=True, guilds=True)
# noinspection PyTypeChecker
bot = Bot(intents=intents, command_prefix=when_mentioned)
log = logging.getLogger("bot")


@bot.event
async def on_ready():
    await init()
    await bot.load_extension("cogs.jsk")
    await bot.load_extension("cogs.bridge")
    await bot.load_extension("cogs.tokens")
    await bot.load_extension("cogs.mod")


@bot.event
async def on_command_error(ctx: commands.Context, error: Exception):
    if isinstance(error, commands.CheckFailure):
        await ctx.send(
            str(error) or "You do not have permission to use this command",
            ephemeral=True,
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.send(str(error) or "Invalid arguments!", ephemeral=True)
    else:
        log.error(f"Caught an unexpected error in {ctx.command.qualified_name}", error)
        await ctx.send("An unexpected error occurred.")


@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: Exception):
    if isinstance(error, app_commands.CommandNotFound):
        await cast(discord.InteractionResponse, interaction.response).send_message(
            "I can't seem to find that command!"
        )
        return

    await on_command_error(await commands.Context.from_interaction(interaction), error)


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
