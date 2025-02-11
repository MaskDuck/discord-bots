import asyncio
import datetime
import discord
import typing
import urllib
import colorsys

import random
from discord.ext import commands, tasks

q = "'"
t = ' now'
n = ''

st_x = 0


def naturalize(number: int) -> int:
    if number > 360:
        return number - 360
    elif number < 0:
        return number + 360
    else:
        return number


def _get_range(x: int, aperture) -> list:
    x = int(x)
    r = list(range(x - aperture, x + aperture))
    r2 = list(map(naturalize, r))
    return r2


def _get_degree(initial, aperture: int = 20):
    mrange = _get_range(initial * 360, aperture=aperture)
    degrees = random.uniform(0, 1) * 360
    while int(degrees) in mrange:
        degrees = random.uniform(0, 1) * 360
    return degrees / 360


def random_color(previous_color: discord.Color = None):
    if previous_color is None:
        previous_color = discord.Color.random()

    prev_h = colorsys.rgb_to_hsv(previous_color.r / 255, previous_color.g / 255, previous_color.b / 255)
    return discord.Color.from_hsv(_get_degree(prev_h[0], aperture=20), random.uniform(0.8, 1), random.uniform(0.8, 1))


def get_complementary(color):
    color = color[1:]
    color = int(color, 16)
    comp_color = 0xFFFFFF ^ color
    comp_color = "#%06X" % comp_color
    return comp_color

color = discord.Color.random()
embeds = []
for _ in range(0, 10):
    color = random_color(color)
    embeds.append(discord.Embed(color=color, title=f'{color}'))

async def do_cotd(ctx: typing.Union[commands.Context, commands.Bot], color: discord.Color = None, manual: bool = False):
    if color is None:
        previous = await getattr(ctx, 'bot', ctx).db.fetchval('SELECT color_int FROM cotd ORDER BY added_at DESC LIMIT 1')
        previous = discord.Color(int(previous)) if previous else None
        color = random_color(previous_color=previous)

    guild = (ctx.bot if isinstance(ctx, commands.Context) else ctx).get_guild(706624339595886683)

    await guild.get_role(800407956323434556).edit(colour=color)
    await guild.get_role(800295689585819659).edit(colour=color)
    log_channel = guild.get_channel(869282490160926790)
    embed = discord.Embed(color=color)
    embed.set_author(icon_url='https://imgur.com/izRBtg9', name='Color of the Day')
    embed.set_image(url=f'https://fakeimg.pl/1200x500/{str(color)[1:]}/{get_complementary(str(color))[1:]}/'
                        f'?text={urllib.parse.quote(f"Today{q}s color is{t if manual is True else n} {color}")}')
    if manual is True:
        embed.set_footer(text=f"Requested by {ctx.author}",
                         icon_url=ctx.author.display_avatar.url)

        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed, delete_after=1)

    await log_channel.send(embed=embed)
    await getattr(ctx, 'bot', ctx).db.execute('INSERT INTO cotd(color_int, added_at) VALUES ($1, $2)', color.value, discord.utils.utcnow())
    return color


class daily_color(commands.Cog):
    """🎨 A role that changes color every day."""

    def __init__(self, bot):
        self.bot = bot

        self.remrole.start()
        self.daily_task.start()

    def cog_unload(self):
        self.daily_task.cancel()
        self.remrole.cancel()

    @tasks.loop(hours=24)
    async def daily_task(self):
        await do_cotd(self.bot, manual=False)

    @daily_task.before_loop
    async def wait_until_midnight(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now().astimezone()
        next_run = now.replace(hour=5, minute=0, second=2)

        if next_run < now:
            next_run += datetime.timedelta(days=1)

        await discord.utils.sleep_until(next_run)

    @commands.command(aliases=["color", "setcolor"])
    @commands.has_permissions(manage_nicknames=True)
    async def cotd(self, ctx, color: typing.Optional[discord.Colour] = None):
        """
        Changes the Color of the day, run the command withour a colour to randomize it.
        """
        await do_cotd(ctx, color, manual=True)

    @tasks.loop(minutes=15)
    async def remrole(self):
        role = self.bot.get_guild(706624339595886683).get_role(851498082033205268)
        for members in role.members:
            date = members.joined_at
            now = discord.utils.utcnow()
            diff = now - date
            hours = diff.total_seconds() / 60 / 60
            if hours >= 336:
                await members.remove_roles(role)
            await asyncio.sleep(5)

    @remrole.before_loop
    async def wait_until_bot_ready(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(daily_color(bot))
