import asyncio
import re
import typing
import unicodedata
import discord

from inspect import Parameter
from typing import Optional
from discord.ext import commands, menus

from DuckBot import errors
from DuckBot.helpers import paginator, time_inputs, constants
from DuckBot.__main__ import DuckBot, CustomContext
from DuckBot.helpers import helper


def setup(bot):
    bot.add_cog(Utility(bot))


class Utility(commands.Cog):
    """
    💬 Text and utility commands, mostly to display information about a server.
    """

    def __init__(self, bot):
        self.bot: DuckBot = bot

    @commands.command(name='charinfo')
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    async def character_info(self, ctx: CustomContext, *, characters: str):
        """Shows you information about a number of characters."""

        def to_string(c):
            digit = f'{ord(c):x}'
            name = unicodedata.name(c, 'Name not found.')
            return f'`\\U{digit:>08}`: {name} - **{c}** \N{EM DASH} ' \
                   f'<http://www.fileformat.info/info/unicode/char/{digit}>'

        msg = '\n'.join(map(to_string, characters))

        menu = menus.MenuPages(paginator.CharacterInformationPageSource(msg.split("\n"), per_page=20),
                               delete_message_after=True)
        await menu.start(ctx)

    @commands.command(aliases=['s', 'send'],
                      help="Speak as if you were me. # URLs/Invites not allowed!")
    @commands.check_any(commands.bot_has_permissions(send_messages=True), commands.is_owner())
    async def say(self, ctx: CustomContext, *, msg: str) -> Optional[discord.Message]:

        results = re.findall(r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|)+",
                             msg)  # HTTP/HTTPS URL regex
        results2 = re.findall(r"(?:https?://)?discord(?:app)?\.(?:com/invite|gg)/[a-zA-Z0-9]+/?",
                              msg)  # Discord invite regex
        if results or results2:
            await ctx.send(
                f"hey, {ctx.author.mention}. Urls or invites aren't allowed!",
                delete_after=10)
            return await ctx.message.delete(delay=10)

        await ctx.message.delete(delay=0)
        if ctx.channel.permissions_for(ctx.author).manage_messages:
            allowed = True
        else:
            allowed = False

        return await ctx.send(msg[0:2000], allowed_mentions=discord.AllowedMentions(everyone=False,
                                                                                    roles=False,
                                                                                    users=allowed),
                              reference=ctx.message.reference,
                              reply=False)

    @commands.command(
        aliases=['a', 'an', 'announce'],
        usage="<channel> <message_or_reply>")
    @commands.check_any(commands.has_permissions(manage_messages=True), commands.is_owner())
    @commands.check_any(commands.bot_has_permissions(send_messages=True, manage_messages=True), commands.is_owner())
    async def echo(self, ctx: CustomContext, channel: typing.Union[discord.TextChannel, int], *,
                   message_or_reply: str = None) \
            -> discord.Message:
        """"
        Echoes a message to another channel
        # If a message is quoted, it will echo the quoted message's content.
        """
        if isinstance(channel, int) and self.bot.is_owner(ctx.author):
            channel = self.bot.get_channel(channel)
        if not channel:
            raise commands.MissingRequiredArgument(Parameter(name='channel', kind=Parameter.POSITIONAL_ONLY))
        if not ctx.message.reference and not message_or_reply:
            raise commands.MissingRequiredArgument(
                Parameter(name='message_or_reply', kind=Parameter.POSITIONAL_ONLY))
        elif ctx.message.reference:
            message_or_reply = ctx.message.reference.resolved.content
        return await channel.send(message_or_reply[0:2000], allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=True))

    @commands.command(
        aliases=['e', 'edit'],
        usage="[new message] [--d|--s]")
    @commands.check_any(commands.has_permissions(manage_messages=True), commands.is_owner())
    @commands.check_any(commands.bot_has_permissions(send_messages=True, manage_messages=True), commands.is_owner())
    async def edit_message(self, ctx, *, new: typing.Optional[str] = '--d'):
        """Quote a bot message to edit it.
        # Append --s at the end to suppress embeds and --d to delete the message
        """
        if ctx.message.reference:
            msg = ctx.message.reference.resolved
            if new.endswith("--s"):
                await msg.edit(content=f"{new[:-3]}", suppress=True)
            elif new.endswith('--d'):
                await msg.delete()
            else:
                await msg.edit(content=new, suppress=False)
            await ctx.message.delete(delay=0.1)
        else:
            raise errors.NoQuotedMessage

    @commands.command(aliases=['uinfo', 'ui', 'whois', 'whoami'])
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    @commands.guild_only()
    async def userinfo(self, ctx: CustomContext, *, member: typing.Optional[discord.Member]):
        """
        Shows a user's information. If not specified, shows your own.
        """
        member = member or ctx.author

        embed = discord.Embed(color=(member.color if member.color != discord.Colour.default() else discord.Embed.Empty))
        embed.set_author(name=member, icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)

        embed.add_field(name=f"{constants.information_source} General information",
                        value=f"**ID:** {member.id}"
                              f"\n**Name:** {member.name}"
                              f"\n╰ **Nick:** {(member.nick or '✖')}"
                              f"\n**Owner:** {ctx.tick(member == member.guild.owner)} • "
                              f"**Bot:** {ctx.tick(member.bot)}", inline=True)

        embed.add_field(name=f"{constants.store_tag} Badges",
                        value=(helper.get_user_badges(member) or "No Badges") + '\u200b', inline=True)

        embed.add_field(name=f"{constants.invite} Created At",
                        value=f"╰ {discord.utils.format_dt(member.created_at, style='f')} "
                              f"({discord.utils.format_dt(member.created_at, style='R')})",
                        inline=False)

        embed.add_field(name=f"{constants.joined} Created At",
                        value=(f"╰ {discord.utils.format_dt(member.joined_at, style='f')} "
                               f"({discord.utils.format_dt(member.joined_at, style='R')})"
                               f"\n\u200b \u200b \u200b \u200b ╰ {constants.moved} **Join Position:** "
                               f"{sorted(ctx.guild.members, key=lambda m: m.joined_at).index(member) + 1}")
                        if member else "Could not get data",
                        inline=False)

        perms = helper.get_perms(member.guild_permissions)
        if perms:
            embed.add_field(name=f"{constants.store_tag} Staff Perms:",
                            value=f"`{'` `'.join(perms)}`", inline=False)

        roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
        if roles:
            embed.add_field(name=f"{constants.roles} Roles:",
                            value=" ".join(roles), inline=False)

        if member.premium_since:
            embed.add_field(name=f"{constants.boost} Boosting since:",
                            value=f"╰ {discord.utils.format_dt(member.premium_since, style='f')} "
                                  f"({discord.utils.format_dt(member.premium_since, style='R')})",
                            inline=False)

        return await ctx.send(embed=embed)

    @commands.command(aliases=['perms'])
    @commands.guild_only()
    async def permissions(self, ctx: CustomContext, target: discord.Member = None) -> discord.Message:
        """
        Shows a user's guild permissions.
        Note: This does not take into account channel overwrites.
        """
        target = target or ctx.me
        allowed = []
        denied = []
        for perm in target.guild_permissions:
            if perm[1] is True:
                allowed.append(ctx.default_tick(perm[1], perm[0].replace('_', ' ').replace('guild', 'server')))
            elif perm[1] is False:
                denied.append(ctx.default_tick(perm[1], perm[0].replace('_', ' ').replace('guild', 'server')))

        embed = discord.Embed()
        embed.set_author(icon_url=target.display_avatar.url, name=target)
        embed.set_footer(icon_url=target.display_avatar.url, text=f"{target.name}'s guild permissions")
        if allowed:
            embed.add_field(name="allowed", value="\n".join(allowed))
        if denied:
            embed.add_field(name="denied", value="\n".join(denied))
        return await ctx.send(embed=embed)

    @commands.command(aliases=["si"])
    @commands.guild_only()
    async def serverinfo(self, ctx: CustomContext, guild: typing.Optional[discord.Guild]):
        """
        Shows the current server's information.
        """
        guilds = [guild if guild and (await self.bot.is_owner(ctx.author)) else ctx.guild]
        source = paginator.ServerInfoPageSource(guilds=guilds, ctx=ctx)
        menu = paginator.ViewPaginator(source=source, ctx=ctx)
        await menu.start()

    @commands.command(aliases=['av', 'pfp'])
    async def avatar(self, ctx: CustomContext, member: typing.Union[discord.Member, discord.User] = None):
        """
        Displays a user's avatar. If not specified, shows your own.
        """
        user: discord.User = member or ctx.author
        embed = discord.Embed(title=user, url=user.display_avatar.url)
        if isinstance(user, discord.Member) and user.guild_avatar:
            embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
            embed.description = f"[avatar]({user.avatar.url if user.avatar else user.default_avatar.url}) | " \
                                f"[server avatar]({user.display_avatar.url})"
        embed.set_image(url=user.display_avatar.url)

        await ctx.send(embed=embed, footer=False)

    @commands.group(invoke_without_command=True, aliases=['em'])
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    async def emoji(self, ctx: CustomContext,
                    custom_emojis: commands.Greedy[typing.Union[discord.Emoji, discord.PartialEmoji]]):
        """
        Makes an emoji bigger and shows it's formatting
        """
        if not custom_emojis:
            raise commands.MissingRequiredArgument(
                Parameter(name='custom_emojis', kind=Parameter.POSITIONAL_ONLY))

        source = paginator.EmojiListPageSource(data=custom_emojis, ctx=ctx)
        menu = paginator.ViewPaginator(source=source, ctx=ctx,
                                       check_embeds=True)
        await menu.start()

    @emoji.command(name="lock")
    @commands.guild_only()
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def emoji_lock(self, ctx: CustomContext, server_emoji: discord.Emoji,
                         roles: commands.Greedy[discord.Role]) -> discord.Message:
        """
        Locks an emoji to one or multiple roles. Input as many roles as you want in the "[roles]..." parameter.
        Note: admin/owner DOES NOT bypass this lock, so be sure to have the role if you wish to unlock the emoji.
        # If the role is removed and re-assigned, the locked emoji will not be visible until you restart your client.
        # To unlock an emoji you can't access, use the `db.emoji unlock <emoji_name>` command
        """
        if not roles:
            raise commands.MissingRequiredArgument(Parameter('role', Parameter.POSITIONAL_ONLY))
        if server_emoji.guild_id != ctx.guild.id:
            return await ctx.send("That emoji is from another server!")
        embed = discord.Embed(description=f"**Restricted access of {server_emoji} to:**"
                                          f"\n{', '.join([r.mention for r in roles])}"
                                          f"\nTo unlock the emoji do `{ctx.clean_prefix} emoji unlock {server_emoji}`"
                                          f"_Note that to do this you will need one of the roles the emoji has been "
                                          f"restricted to. \nNo, admin permissions don't bypass this lock._")
        embed.set_footer()
        await ctx.send(embed=embed)
        await server_emoji.edit(roles=roles)

    @emoji.group(name="unlock", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def emoji_unlock(self, ctx: CustomContext, server_emoji: discord.Emoji) -> discord.Message:
        """
        Unlocks a locked emoji.
        # Note that you can also pass an emoji name, like so:
        # db.emoji lock 💥
        # ✅ db.emoji unlock boom
        # ❌ db.emoji unlock :boom:
        # ^^^^ Only for example! emoji must be a custom one, not a default one.
        """
        if server_emoji.guild_id != ctx.guild.id:
            return await ctx.send("That emoji is from another server!")
        await server_emoji.edit(roles=[])
        embed = discord.Embed(title="Successfully unlocked emoji!",
                              description=f"**Allowed {server_emoji} to @everyone**")
        return await ctx.send(embed=embed)

    @emoji_unlock.command(name="all")
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def emoji_unlock_all(self, ctx: CustomContext):
        """
        Unlocks all locked emojis in the current server.
        """
        async with ctx.typing():
            unlocked = []
            for emoji in ctx.guild.emojis:
                if emoji.roles:
                    await emoji.edit(roles=[], reason=f"Unlock all emoji requested by {ctx.author} ({ctx.author.id})")
                    unlocked.append(emoji)
                    await asyncio.sleep(1)
            await ctx.send(f"Done! Unlocked {len(unlocked)} emoji(s)"
                           f"\n {' '.join([str(em) for em in unlocked])}")

    @emoji.command(name="steal", hidden=True, aliases=['s'])
    @commands.is_owner()
    async def emoji_steal(self, ctx, index: int = 1):
        if not ctx.message.reference:
            raise errors.NoQuotedMessage

        custom_emoji = re.compile(r"<a?:[a-zA-Z0-9_]+:[0-9]+>")
        emojis = custom_emoji.findall(ctx.message.reference.resolved.content)
        if not emojis:
            raise errors.NoEmojisFound

        try:
            emoji = await commands.PartialEmojiConverter().convert(ctx, emojis[index - 1])
        except IndexError:
            return await ctx.send(f"Emoji out of index {index}/{len(emojis)}!"
                                  f"\nIndex must be lower or equal to {len(emojis)}")
        file = await emoji.read()
        guild = self.bot.get_guild(831313673351593994)
        emoji = await guild.create_custom_emoji(name=emoji.name, image=file, reason="stolen emoji KEK")
        try:
            await ctx.message.add_reaction(emoji)
        except discord.NotFound:
            pass

    @emoji.command(name="clone", usage="<server_emoji>")
    @commands.has_permissions(manage_emojis=True)
    @commands.bot_has_permissions(manage_emojis=True)
    async def emoji_clone(self, ctx: CustomContext,
                          server_emoji: typing.Optional[typing.Union[discord.Embed,
                                                                     discord.PartialEmoji]],
                          index: int = 1):
        """
        Clones an emoji into the current server.
        # To steal an emoji from someone else, quote their message to grab the emojis from there.
        # If the quoted message has multiple emojis, input an index number to specify the emoji, for example, doing "%PRE%emoji 5" will steal the 5th emoji from the message.
        None: Index is only for when stealing emojis from other people.
        """
        if ctx.message.reference:
            custom_emoji = re.compile(r"<a?:[a-zA-Z0-9_]+:[0-9]+>")
            emojis = custom_emoji.findall(ctx.message.reference.resolved.content)
            if not emojis:
                raise errors.NoEmojisFound
            try:
                server_emoji = await commands.PartialEmojiConverter().convert(ctx, emojis[index - 1])
            except IndexError:
                return await ctx.send(f"Emoji out of index {index}/{len(emojis)}!"
                                      f"\nIndex must be lower or equal to {len(emojis)}")

        if not server_emoji:
            raise commands.MissingRequiredArgument(
                Parameter(name='server_emoji', kind=Parameter.POSITIONAL_ONLY))

        file = await server_emoji.read()
        guild = ctx.guild
        server_emoji = await guild.create_custom_emoji(name=server_emoji.name, image=file,
                                                       reason=f"Cloned emoji, requested by {ctx.author}")
        await ctx.send(f"Done! cloned {server_emoji}")

    @emoji.command(usage="", name='list')
    @commands.guild_only()
    async def emoji_list(self, ctx: CustomContext, guild: typing.Optional[typing.Union[discord.Guild,
                                                                                       typing.Literal['bot']]]):
        """ Lists this server's emoji """
        target_guild = guild if isinstance(guild, discord.Guild) and (await self.bot.is_owner(ctx.author)) \
            else 'bot' if isinstance(guild, str) and (await self.bot.is_owner(ctx.author)) else ctx.guild
        emojis = target_guild.emojis if isinstance(target_guild, discord.Guild) else self.bot.emojis

        emotes = [f"{str(e)} **|** `{e.id}` **|** [{e.name}]({e.url})" for e in emojis]
        menu = paginator.ViewPaginator(paginator.ServerEmotesEmbedPage(data=emotes,
                                                                       guild=(target_guild if isinstance(target_guild,
                                                                                                         discord.Guild)
                                                                              else ctx.bot)), ctx=ctx)
        await menu.start()

    @commands.command(aliases=['uuid'])
    @commands.bot_has_permissions(send_messages=True, embed_links=True)
    async def minecraft_uuid(self, ctx: CustomContext, *, username: str) \
            -> typing.Optional[discord.Message]:
        """ Fetches the UUID of a minecraft user from the Mojang API, and avatar from craftavatar.com """
        argument = username
        async with self.bot.session.get(f"https://api.mojang.com/users/profiles/minecraft/{argument}") as cs:
            if cs.status == 204:
                raise commands.BadArgument('That is not a valid Minecraft UUID!')
            elif cs.status != 200:
                raise commands.BadArgument('Something went wrong...')
            res = await cs.json()
            user = res["name"]
            uuid = res["id"]
            embed = discord.Embed(description=f"**UUID:** `{uuid}`")
            embed.set_author(icon_url=f'https://crafatar.com/avatars/{uuid}?size=128&overlay=true', name=user)
            return await ctx.send(embed=embed)

    @commands.command(name="commands")
    async def _commands(self, ctx: CustomContext) -> discord.Message:
        """
        Shows all the bot commands, even the ones you can't run.
        """

        ignored_cogs = ("Bot Management", "Jishaku")

        def divide_chunks(str_list, n):
            for i in range(0, len(str_list), n):
                yield str_list[i:i + n]

        shown_commands = [c.name for c in self.bot.commands if c.cog_name not in ignored_cogs]
        ml = max([len(c.name) for c in self.bot.commands if c.cog_name not in ignored_cogs]) + 1

        all_commands = list(divide_chunks(shown_commands, 3))
        all_commands = '\n'.join([''.join([f"{x}{' ' * (ml - len(x))}" for x in c]).strip() for c in all_commands])

        return await ctx.send(embed=discord.Embed(title=f"Here are ALL my commands ({len(shown_commands)})",
                                                  description=f"```fix\n{all_commands}\n```"))

    @commands.command(name="in")
    async def _in_command(self, ctx, *, relative_time: time_inputs.ShortTime):
        """
        Shows a time in everyone's time-zone
          note that: `relative_time` must be a short time!
        for example: 1d, 5h, 3m or 25s, or a combination of those, like 3h5m25s (without spaces between these times)
        """

        await ctx.send(f"{discord.utils.format_dt(relative_time.dt, style='F')} "
                       f"({discord.utils.format_dt(relative_time.dt, style='R')})")

    @commands.command()
    async def afk(self, ctx: CustomContext, *, reason: commands.clean_content = '...'):
        if ctx.author.id in self.bot.afk_users and ctx.author.id in self.bot.auto_un_afk and self.bot.auto_un_afk[ctx.author.id] is True:
            return
        if ctx.author.id not in self.bot.afk_users:
            await self.bot.db.execute('INSERT INTO afk (user_id, start_time, reason) VALUES ($1, $2, $3) '
                                      'ON CONFLICT (user_id) DO UPDATE SET start_time = $2, reason = $3',
                                      ctx.author.id, ctx.message.created_at, reason[0:1800])
            self.bot.afk_users[ctx.author.id] = True
            await ctx.send(f'**You are now afk!** {constants.roo_sleep}'
                           f'\n**with reason:** {reason}')
        else:
            self.bot.afk_users.pop(ctx.author.id)

            info = await self.bot.db.fetchrow('SELECT * FROM afk WHERE user_id = $1', ctx.author.id)
            await self.bot.db.execute('INSERT INTO afk (user_id, start_time, reason) VALUES ($1, null, null) '
                                      'ON CONFLICT (user_id) DO UPDATE SET start_time = null, reason = null', ctx.author.id)

            await ctx.channel.send(f'**Welcome back, {ctx.author.mention}, afk since: {discord.utils.format_dt(info["start_time"], "R")}**'
                                   f'\n**With reason:** {info["reason"]}', delete_after=10)

            await ctx.message.add_reaction('👋')

    @commands.command(name='auto-afk-remove', aliases=['autoafk', 'aafk'])
    async def auto_un_afk(self, ctx: CustomContext, mode: bool = None):
        """
        Toggles weather to remove the AFK status automatically or not.
        mode: either enabled or disabled. If none, it will toggle it.
        """
        mode = mode or (False if (ctx.author.id in self.bot.auto_un_afk and self.bot.auto_un_afk[ctx.author.id] is True) or ctx.author.id not in self.bot.auto_un_afk else True)
        self.bot.auto_un_afk[ctx.author.id] = mode
        await self.bot.db.execute('INSERT INTO afk (user_id, auto_un_afk) VALUES ($1, $2) '
                                  'ON CONFLICT (user_id) DO UPDATE SET auto_un_afk = $2', ctx.author.id, mode)
        return await ctx.send(f'{"Enabled" if mode is True else "Disabled"} automatic AFK removal.'
                              f'\n{"**Remove your AFK status by running the `afk` command while being AFK**" if mode is False else ""}')
