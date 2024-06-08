import logging

from discord.ext import commands
from jishaku.features.filesystem import FilesystemFeature
from jishaku.features.guild import GuildFeature
from jishaku.features.invocation import InvocationFeature
from jishaku.features.management import ManagementFeature
from jishaku.features.python import PythonFeature
from jishaku.features.root_command import RootCommand
from jishaku.features.shell import ShellFeature

log = logging.getLogger("argon.jishaku")


class Jishaku(
    GuildFeature,
    FilesystemFeature,
    InvocationFeature,
    ShellFeature,
    PythonFeature,
    ManagementFeature,
    RootCommand,
):
    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Jishaku(bot=bot))
