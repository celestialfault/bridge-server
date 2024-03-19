import os

import discord
from dotenv import load_dotenv
from discord.ext.commands import Bot, when_mentioned

from db import init

load_dotenv()
intents = discord.Intents(messages=True, message_content=True, guilds=True)
bot = Bot(intents=intents, command_prefix=when_mentioned)


@bot.event
async def on_ready():
    await init()
    try:
        # noinspection PyPackageRequirements
        import jishaku
    except ImportError:
        pass
    else:
        await bot.load_extension("jishaku")
    await bot.load_extension("cogs.bridge")
    await bot.load_extension("cogs.tokens")


bot.run(os.environ["DISCORD_TOKEN"])