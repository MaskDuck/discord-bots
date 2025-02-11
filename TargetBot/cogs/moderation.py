import argparse
import asyncio
import datetime
import io
import re
import shlex
import typing
import yaml
from collections import Counter

import discord
from discord.ext import commands, menus


class Arguments(argparse.ArgumentParser):
    def error(self, message):
        raise RuntimeError(message)


class ActionReason(commands.Converter):
    async def convert(self, ctx, argument):
        ret = f'{ctx.author} (ID: {ctx.author.id}): {argument}'

        if len(ret) > 512:
            reason_max = 512 - len(ret) + len(argument)
            raise commands.BadArgument(f'Reason is too long ({len(argument)}/{reason_max})')
        return ret


def safe_reason_append(base, to_append):
    appended = base + f'({to_append})'
    if len(appended) > 512:
        return base
    return appended


class BanEmbed(menus.ListPageSource):
    def __init__(self, data, per_page=15):
        super().__init__(data, per_page=per_page)

    async def format_page(self, menu, entries):
        embed = discord.Embed(title=f"Server bans ({len(entries)})",
                              description="\n".join(entries))
        embed.set_footer(text=f"To unban do !unban [entry]\nMore user info do !baninfo [entry]")
        return embed


class Confirm(menus.Menu):
    def __init__(self, msg):
        super().__init__(timeout=30.0, delete_message_after=True)
        self.msg = msg
        self.result = None

    async def send_initial_message(self, ctx, channel):
        return await channel.send(self.msg)

    @menus.button('\N{WHITE HEAVY CHECK MARK}')
    async def do_confirm(self, payload):
        self.result = True
        self.stop()

    @menus.button('\N{CROSS MARK}')
    async def do_deny(self, payload):
        self.result = False
        self.stop()

    async def prompt(self, ctx):
        await self.start(ctx, wait=True)
        return self.result


def can_execute_action(ctx, user, target):
    return user.id == ctx.bot.owner_id or \
           user == ctx.guild.owner or \
           user.top_role > target.top_role


class MemberID(commands.Converter):
    async def convert(self, ctx, argument):
        try:
            m = await commands.MemberConverter().convert(ctx, argument)
        except commands.BadArgument:
            try:
                member_id = int(argument, base=10)
            except ValueError:
                raise commands.BadArgument(f"{argument} is not a valid member or member ID.") from None
            else:
                m = await ctx.bot.get_or_fetch_member(ctx.guild, member_id)
                if m is None:
                    # hackban case
                    return type('_Hackban', (), {'id': member_id, '__str__': lambda s: f'Member ID {s.id}'})()

        if not can_execute_action(ctx, ctx.author, m):
            raise commands.BadArgument('You cannot do this action on this user due to role hierarchy.')
        return m


class BannedMember(commands.Converter):
    async def convert(self, ctx, argument):
        if argument.isdigit():
            member_id = int(argument, base=10)
            try:
                return await ctx.guild.fetch_ban(discord.Object(id=member_id))
            except discord.NotFound:
                raise commands.BadArgument('This member has not been banned before.') from None

        ban_list = await ctx.guild.bans()
        entity = discord.utils.find(lambda u: str(u.user) == argument, ban_list)

        if entity is None:
            raise commands.BadArgument('This member has not been banned before.')
        return entity


class Moderation(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        # ------------- YAML STUFF -------------#
        with open(r'files/config.yaml') as file:
            full_yaml = yaml.full_load(file)
            staff_roles = []
            for roleid in full_yaml['StaffRoles']:
                staff_roles.append(self.bot.get_guild(717140270789033984).get_role(roleid))
        self.staff_roles = staff_roles
        self.yaml_data = full_yaml

    @staticmethod
    async def do_removal(ctx: commands.Context, limit: int, predicate, *, before=None, after=None):
        if limit > 2000:
            return await ctx.send(f'Too many messages to search given ({limit}/2000)')

        if before is None:
            before = ctx.message
        else:
            before = discord.Object(id=before)

        if after is not None:
            after = discord.Object(id=after)

        try:
            await ctx.message.delete()
            deleted = await ctx.channel.purge(limit=limit, before=before, after=after, check=predicate)
        except discord.Forbidden:
            return await ctx.send('I do not have permissions to delete messages.')
        except discord.HTTPException as e:
            return await ctx.send(f'Error: {e} (try a smaller search?)')

        spammers = Counter(m.author.display_name for m in deleted)
        deleted = len(deleted)
        messages = [f'{deleted} message{" was" if deleted == 1 else "s were"} removed.']
        if deleted:
            messages.append('')
            spammers = sorted(spammers.items(), key=lambda t: t[1], reverse=True)
            messages.extend(f'**{name}**: {count}' for name, count in spammers)

        to_send = '\n'.join(messages)

        if len(to_send) > 2000:
            await ctx.send(f'Successfully removed {deleted} messages.', delete_after=10)
        else:
            await ctx.send(to_send, delete_after=10)

    # --------------- FUNCTIONS ---------------#

    async def perms_error(self, ctx):
        await ctx.message.add_reaction('🚫')
        await asyncio.sleep(self.yaml_data['ReactionTimeout'])
        await ctx.message.delete(delay=1)

    async def error_message(self, ctx, message):
        embed = discord.Embed(color=ctx.me.color)
        embed.set_author(name=message, icon_url='https://i.imgur.com/OAmzSGF.png')
        await ctx.send(embed=embed, delete_after=self.yaml_data['ErrorMessageTimeout'])
        await asyncio.sleep(self.yaml_data['ErrorMessageTimeout'])
        await ctx.message.delete(delay=1)

    @commands.command()
    async def invites(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        invites = 0
        for invite in await ctx.guild.invites():
            if invite.inviter == member:
                invites += invite.uses
        embed = discord.Embed(description=f"{member} has invited **{invites}** member(s) to **{ctx.guild.name}**!",
                              color=0x2F3136)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------#
    # ------------------------ KICK ------------------------------#
    # ------------------------------------------------------------#

    @commands.command()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if member == None:
            await self.error_message(ctx, 'You must specify a member to kick')
            return
        elif member == ctx.author:
            await self.error_message(ctx, 'You can\'t kick yourself')
            return
        elif member.top_role >= ctx.me.top_role:
            await self.error_message(ctx, 'I\'m not high enough in role hierarchy to kick that member!')
            return
        if member.top_role <= ctx.author.top_role:
            if member.guild_permissions.ban_members == False or member.guild_permissions.kick_members == False:
                try:
                    mem_embed = discord.Embed(
                        description=f"**{ctx.message.author}** has kicked you from **{ctx.guild.name}**",
                        color=ctx.me.color)
                    if reason: mem_embed.set_footer(text=f'reason: {reason}')
                    await member.send(embed=mem_embed)
                    await member.kick(reason=reason)
                    if reason:
                        embed = discord.Embed(description=f"""{ctx.author.mention} kicked {member.mention}
```reason: {reason}```""", color=ctx.me.color)
                    else:
                        embed = discord.Embed(description=f"""{ctx.author.mention} kicked {member.mention}""",
                                              color=ctx.me.color)
                    embed.set_footer(text=f'{member.id} | DM sent: ✅')
                    await ctx.send(embed=embed)
                except discord.HTTPException:
                    await member.kick(reason=reason)
                    if reason:
                        embed = discord.Embed(description=f"""{ctx.author.mention} kicked {member.mention}
```reason: {reason}```""", color=ctx.me.color)
                    else:
                        embed = discord.Embed(description=f"""{ctx.author.mention} kicked {member.mention}""",
                                              color=ctx.me.color)
                    embed.set_footer(text=f'{member.id} | DM sent: ❌')
                    await ctx.send(embed=embed)
            else:
                await self.error_message(ctx, 'you can\'t kick another moderator')
                return
        else:
            await self.error_message(ctx, 'Member is higher than you in role hierarchy')
            return

    @kick.error
    async def kick_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure): await self.perms_error(ctx)

    # -----------------------------------------------------------#
    # ------------------------ BAN ------------------------------#
    # -----------------------------------------------------------#

    @commands.command()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return
        if member == None:
            await self.error_message(ctx, 'You must specify a member to ban')
            return
        elif member == ctx.author:
            await self.error_message(ctx, 'You can\'t ban yourself')
            return
        elif member.top_role >= ctx.me.top_role:
            await self.error_message(ctx, 'I\'m not high enough in role hierarchy to ban that member!')
            return
        if member.top_role <= ctx.author.top_role:
            if member.guild_permissions.ban_members == False or member.guild_permissions.kick_members == False:
                try:
                    mem_embed = discord.Embed(
                        description=f"**{ctx.message.author}** has banned you from **{ctx.guild.name}**",
                        color=ctx.me.color)
                    if reason: mem_embed.set_footer(text=f'reason: {reason}')
                    await member.send(embed=mem_embed)
                    await member.ban(reason=reason)
                    if reason:
                        embed = discord.Embed(description=f"""{ctx.author.mention} banned {member.mention}
```reason: {reason}```""", color=ctx.me.color)
                    else:
                        embed = discord.Embed(description=f"""{ctx.author.mention} banned {member.mention}""",
                                              color=ctx.me.color)
                    embed.set_footer(text=f'{member.id} | DM sent: ✅')
                    await ctx.send(embed=embed)
                except discord.HTTPException:
                    await member.ban(reason=reason)
                    if reason:
                        embed = discord.Embed(description=f"""{ctx.author.mention} banned {member.mention}
```reason: {reason}```""", color=ctx.me.color)
                    else:
                        embed = discord.Embed(description=f"""{ctx.author.mention} banned {member.mention}""",
                                              color=ctx.me.color)
                    embed.set_footer(text=f'{member.id} | DM sent: ❌')
                    await ctx.send(embed=embed)
            else:
                await self.error_message(ctx, 'you can\'t ban another moderator!')
                return

        else:
            await self.error_message(ctx, 'Member is higher than you in role hierarchy')
            return

    @ban.error
    async def ban_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure):
            await self.perms_error(ctx)

    # ------------------------------------------------------------#
    # ------------------------ NICK ------------------------------#
    # ------------------------------------------------------------#

    @commands.command(aliases=['sn', 'nick'])
    async def setnick(self, ctx, member: typing.Optional[discord.Member], *, new: typing.Optional[str] = 'None'):
        if member == None:
            if ctx.channel.permissions_for(ctx.author).manage_nicknames:
                await ctx.send("`!nick [member] (newNick)` - You must specify a member", delete_after=10)
                await asyncio.sleep(10)
                await ctx.message.delete()
            return
        if new == 'None':
            new = f'{member.name}'
        else:
            new = new
        old = f'{member.nick}'
        if old == 'None':
            old = f'{member.name}'
        else:
            old = old
        if member == ctx.author and ctx.channel.permissions_for(ctx.author).change_nickname:
            try:
                await member.edit(nick=new)
                await ctx.send(f"""✏ {ctx.author.mention} nick for {member}
**`{old}`** -> **`{new}`**""")
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    return
            except discord.Forbidden:
                await self.error_message(ctx, 'Bot not high enough in role hierarchy')
                return
            except discord.HTTPException:
                await ctx.message.add_reaction('#️⃣')
                await ctx.message.add_reaction('3️⃣')
                await ctx.message.add_reaction('2️⃣')
                return
        elif ctx.channel.permissions_for(ctx.author).manage_nicknames:
            if member.top_role >= ctx.author.top_role:
                await self.error_message(ctx, "⚠ Cannot edit nick for members equal or above yourself!")
                return
            try:
                await member.edit(nick=new)
                await ctx.send(f"""✏ {ctx.author.mention} edited nick for **{member}**
**`{old}`** -> **`{new}`**""")
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    return
            except discord.Forbidden:
                await self.error_message(ctx, 'Bot not high enough in role hierarchy')
                return
            except discord.HTTPException:
                await ctx.message.add_reaction('#️⃣')
                await ctx.message.add_reaction('3️⃣')
                await ctx.message.add_reaction('2️⃣')
        elif member == ctx.author and ctx.channel.permissions_for(ctx.author).change_nickname:
            await self.error_message(ctx, f"""You can only change your own nick!
> !nick {ctx.author.mention} `<new nick>`""")
            return
        else:
            await self.perms_error(ctx)

    # -------------------------------------------------------------#
    # ------------------------ PURGE ------------------------------#
    # -------------------------------------------------------------#

    @commands.group(aliases=['purge', 'clear', 'delete', 'clean'])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def remove(self, ctx, search: typing.Optional[int] = 100):
        """```yaml
        Removes messages that meet a criteria. In order to use this command, you must have Manage Messages permissions.

        Remember that the bot needs Manage Messages as well. These commands cannot be used in a private message.

        When the command is done doing its work, you will get a message detailing which users got removed and how many messages got removed.

        Note: If ran without any sub-commands, it will remove all messages that are NOT pinned to the channel. use "remove all <amount>" to remove everything
        ```
        """

        if ctx.invoked_subcommand is None:
            await self.do_removal(ctx, search, lambda e: not e.pinned)

    @remove.command(aliases=['embed'])
    async def embeds(self, ctx, search=100):
        """Removes messages that have embeds in them."""
        await self.do_removal(ctx, search, lambda e: len(e.embeds))

    @remove.command()
    async def files(self, ctx, search=100):
        """Removes messages that have attachments in them."""
        await self.do_removal(ctx, search, lambda e: len(e.attachments))

    @remove.command()
    async def images(self, ctx, search=100):
        """Removes messages that have embeds or attachments."""
        await self.do_removal(ctx, search, lambda e: len(e.embeds) or len(e.attachments))

    @remove.command(name='all')
    async def remove_remove_all(self, ctx, search=100):
        """Removes all messages."""
        await self.do_removal(ctx, search, lambda e: True)

    @remove.command()
    async def user(self, ctx, member: discord.Member, search=100):
        """Removes all messages by the member."""
        await self.do_removal(ctx, search, lambda e: e.author == member)

    @remove.command()
    async def contains(self, ctx, *, text: str):
        """Removes all messages containing a substring.
        The substring must be at least 3 characters long.
        """
        if len(text) < 3:
            await ctx.send('The substring length must be at least 3 characters.')
        else:
            await self.do_removal(ctx, 100, lambda e: text in e.content)

    @remove.command(name='bot', aliases=['bots'])
    async def remove_bot(self, ctx, prefix: typing.Optional[str] = None, search=100):
        """Removes a bot user's messages and messages with their optional prefix."""

        def predicate(m):
            return (m.webhook_id is None and m.author.bot) or (prefix and m.content.startswith(prefix))

        await self.do_removal(ctx, search, predicate)

    @remove.command(name='emoji', aliases=['emojis'])
    async def remove_emoji(self, ctx, search=100):
        """Removes all messages containing custom emoji."""
        custom_emoji = re.compile(r'<a?:[a-zA-Z0-9_]+:([0-9]+)>')

        def predicate(m):
            return custom_emoji.search(m.content)

        await self.do_removal(ctx, search, predicate)

    @remove.command(name='reactions')
    async def remove_reactions(self, ctx, search=100):
        """Removes all reactions from messages that have them."""

        if search > 2000:
            return await ctx.send(f'Too many messages to search for ({search}/2000)')

        total_reactions = 0
        async for message in ctx.history(limit=search, before=ctx.message):
            if len(message.reactions):
                total_reactions += sum(r.count for r in message.reactions)
                await message.clear_reactions()

        await ctx.send(f'Successfully removed {total_reactions} reactions.')

    @remove.group()
    async def custom(self, ctx, *, args: str):
        """A more advanced purge command.
        do "%PRE%help remove custom" for usage.
        """
        parser = Arguments(add_help=False, allow_abbrev=False)
        parser.add_argument('--user', nargs='+')
        parser.add_argument('--contains', nargs='+')
        parser.add_argument('--starts', nargs='+')
        parser.add_argument('--ends', nargs='+')
        parser.add_argument('--or', action='store_true', dest='_or')
        parser.add_argument('--not', action='store_true', dest='_not')
        parser.add_argument('--emoji', action='store_true')
        parser.add_argument('--bot', action='store_const', const=lambda m: m.author.bot)
        parser.add_argument('--embeds', action='store_const', const=lambda m: len(m.embeds))
        parser.add_argument('--files', action='store_const', const=lambda m: len(m.attachments))
        parser.add_argument('--reactions', action='store_const', const=lambda m: len(m.reactions))
        parser.add_argument('--search', type=int)
        parser.add_argument('--after', type=int)
        parser.add_argument('--before', type=int)

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            await ctx.send(str(e))
            return

        predicates = []
        if args.bot:
            predicates.append(args.bot)

        if args.embeds:
            predicates.append(args.embeds)

        if args.files:
            predicates.append(args.files)

        if args.reactions:
            predicates.append(args.reactions)

        if args.emoji:
            custom_emoji = re.compile(r'<:(\w+):(\d+)>')
            predicates.append(lambda m: custom_emoji.search(m.content))

        if args.user:
            users = []
            converter = commands.MemberConverter()
            for u in args.user:
                try:
                    user = await converter.convert(ctx, u)
                    users.append(user)
                except Exception as e:
                    await ctx.send(str(e))
                    return

            predicates.append(lambda m: m.author in users)

        if args.contains:
            predicates.append(lambda m: any(sub in m.content for sub in args.contains))

        if args.starts:
            predicates.append(lambda m: any(m.content.startswith(s) for s in args.starts))

        if args.ends:
            predicates.append(lambda m: any(m.content.endswith(s) for s in args.ends))

        op = all if not args._or else any

        def predicate(m):
            r = op(p(m) for p in predicates)
            if args._not:
                return not r
            return r

        if args.after:
            if args.search is None:
                args.search = 2000

        if args.search is None:
            args.search = 100

        args.search = max(0, min(2000, args.search))  # clamp from 0-2000
        await self.do_removal(ctx, args.search, predicate, before=args.before, after=args.after)

    @custom.command(name="readme")
    async def remove_custom_readme(self, ctx):
        """A more advanced purge command.
        This command uses a powerful "command line" syntax.
        Most options support multiple values to indicate 'any' match.
        If the value has spaces it must be quoted.
        The messages are only deleted if all options are met unless
        the --or flag is passed, in which case only if any is met.

        The following options are valid.
         --user: A mention or name of the user to remove.
         --contains: A substring to search for in the message.
         --starts: A substring to search if the message starts with.
         --ends: A substring to search if the message ends with.
         --search: Messages to search. Default 100. Max 2000.
         --after: Messages after this message ID.
         --before: Messages before this message ID.

        Flag options (no arguments):
         --bot: Check if it's a bot user.
         --embeds: Checks for embeds.
         --files: Checks for attachments.
         --emoji: Checks for custom emoji.
         --reactions: Checks for reactions.
         --or: Use logical OR for ALL options.
         --not: Use logical NOT for ALL options.
        """
        await ctx.send("hi")

    @commands.command()
    async def cleanup(self, ctx, amount: int = 25):
        """
        Cleans up the bots messages. it defaults to 25 messages. if you or the bot don't have manage_messages permission, the search will be limited to 25 messages.
        """
        if amount > 25:
            if not ctx.channel.permissions_for(ctx.author).manage_messages:
                await ctx.send("You must have `manage_messages` permission to perform a search greater than 25")
                return
            if not ctx.channel.permissions_for(ctx.me).manage_messages:
                await ctx.send("I need the `manage_messages` permission to perform a search greater than 25")
                return

        if ctx.channel.permissions_for(ctx.me).manage_messages:
            prefix = '!'

            def check(msg):
                return (msg.author == ctx.me or msg.content.startswith(prefix)) and not msg.reference

            deleted = await ctx.channel.purge(limit=amount, check=check)
        else:
            def check(msg):
                return (msg.author == ctx.me) and not msg.reference

            deleted = await ctx.channel.purge(limit=amount, check=check, bulk=False)
        spammers = Counter(m.author.display_name for m in deleted)
        deleted = len(deleted)
        messages = [f'{deleted} message{" was" if deleted == 1 else "s were"} removed.']
        if deleted:
            messages.append('')
            spammers = sorted(spammers.items(), key=lambda t: t[1], reverse=True)
            messages.extend(f'**{name}**: {count}' for name, count in spammers)

        to_send = '\n'.join(messages)
        if len(to_send) > 2000:
            await ctx.send(f'Successfully removed {deleted} messages.', delete_after=10)
        else:
            await ctx.send(to_send, delete_after=10)

    # ------------------------------------------------------------#
    # ------------------------ MUTE ------------------------------#
    # ------------------------------------------------------------#

    @commands.command()
    async def mute(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return
        if member == None:
            await self.error_message(ctx, 'You must specify a member to mute')
            return
        muterole = self.bot.get_guild(717140270789033984).get_role(self.yaml_data['MuteRole'])
        if muterole in member.roles:
            await self.error_message(ctx, f'{member} is already muted')
            return
        try:
            await member.add_roles(muterole)
            mem_embed = discord.Embed(color=ctx.me.color)
            mem_embed.set_author(name=f"You've been muted by {ctx.author}", icon_url='https://i.imgur.com/hKNGsMb.png')
            mem_embed.set_image(url='https://i.imgur.com/hXbvCT4.png')
            if reason: mem_embed.set_footer(text=f'reason: {reason}')
            await member.send(embed=mem_embed)
            if reason:
                embed = discord.Embed(description=f"""{ctx.author.mention} muted {member.mention} indefinitely...
```reason: {reason}```""", color=ctx.me.color)
            else:
                embed = discord.Embed(description=f"""{ctx.author.mention} muted {member.mention} indefinitely...""",
                                      color=ctx.me.color)
            await ctx.send(embed=embed)
        except:
            await self.error_message(ctx, 'something went wrong...')

    # -------------------------------------------------------------#
    # ------------------------ UNMUTE -----------------------------#
    # -------------------------------------------------------------#

    @commands.command()
    async def unmute(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return
        if member == None:
            await self.error_message(ctx, 'You must specify a member to unmute')
            return
        muterole = ctx.guild.get_role(self.yaml_data['MuteRole'])
        if muterole not in member.roles:
            await self.error_message(ctx, f'{member} is not muted')
            return
        try:
            await member.remove_roles(muterole)
            mem_embed = discord.Embed(color=ctx.me.color)
            mem_embed.set_author(name=f"You've been unmuted by {ctx.author}",
                                 icon_url='https://i.imgur.com/m1MtOVS.png')
            mem_embed.set_image(url='https://i.imgur.com/23XECtg.png')
            if reason: mem_embed.set_footer(text=f'reason: {reason}')
            await member.send(embed=mem_embed)
            if reason:
                embed = discord.Embed(description=f"""{ctx.author.mention} unmuted {member.mention}
```reason: {reason}```""", color=ctx.me.color)
            else:
                embed = discord.Embed(description=f"""{ctx.author.mention} unmuted {member.mention}""",
                                      color=ctx.me.color)
            await ctx.send(embed=embed)
        except:
            await self.error_message(ctx, 'something went wrong...')

    # -----------------------------------------------------------------#
    # ------------------------ DENYMEDIA ------------------------------#
    # -----------------------------------------------------------------#

    @commands.command(aliases=['nomedia', 'noimages', 'denyimages', 'noimg', 'md', 'mediaban', 'nm', 'mb', 'mban'])
    async def denymedia(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return
        if member == None:
            await self.error_message(ctx, 'You must specify a member to deny media to')
            return
        muterole = self.bot.get_guild(717140270789033984).get_role(self.yaml_data['noMediaRole'])
        if muterole in member.roles:
            await self.error_message(ctx, f'{member} is already in deny media')
            return
        try:
            await member.add_roles(muterole)
            mem_embed = discord.Embed(color=ctx.me.color)
            mem_embed.set_author(name=f"You've been denied permissions to send media by {ctx.author}",
                                 icon_url='https://i.imgur.com/hKNGsMb.png')
            if reason: mem_embed.set_footer(text=f'reason: {reason}')
            await member.send(embed=mem_embed)
            if reason:
                embed = discord.Embed(description=f"""{ctx.author.mention} denied media pemrs to {member.mention}
```reason: {reason}```""", color=ctx.me.color)
            else:
                embed = discord.Embed(description=f"""{ctx.author.mention} denied media pemrs to {member.mention}""",
                                      color=ctx.me.color)
            await ctx.send(embed=embed)
        except:
            await self.error_message(ctx, 'something went wrong...')

    # -----------------------------------------------------------------#
    # ------------------------ ALLOWMEDIA -----------------------------#
    # -----------------------------------------------------------------#

    @commands.command(
        aliases=['yesmedia', 'yesimages', 'allowimages', 'yesimg', 'ma', 'mediaunban', 'ym', 'mub', 'munban'])
    async def allowmedia(self, ctx, member: typing.Optional[discord.Member] = None, *, reason=None):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return
        if member == None:
            await self.error_message(ctx, 'You must specify a member deny media to')
            return
        muterole = ctx.guild.get_role(self.yaml_data['noMediaRole'])
        if muterole not in member.roles:
            await self.error_message(ctx, f'{member} is not in deny media')
            return
        try:
            await member.remove_roles(muterole)
            mem_embed = discord.Embed(color=ctx.me.color)
            mem_embed.set_author(name=f"You've been allowed permissions to send media by {ctx.author}",
                                 icon_url='https://i.imgur.com/m1MtOVS.png')
            if reason: mem_embed.set_footer(text=f'reason: {reason}')
            await member.send(embed=mem_embed)
            if reason:
                embed = discord.Embed(description=f"""{ctx.author.mention} returned media pemrs to {member.mention}
```reason: {reason}```""", color=ctx.me.color)
            else:
                embed = discord.Embed(description=f"""{ctx.author.mention} returned media pemrs to {member.mention}""",
                                      color=ctx.me.color)
            await ctx.send(embed=embed)
        except:
            await self.error_message(ctx, 'something went wrong...')

    # ---------------------------------------------------------------#
    # ------------------------ LOCKDOWN -----------------------------#
    # ---------------------------------------------------------------#

    @commands.command(aliases=['lock', 'ld'])
    @commands.has_permissions(manage_channels=True)
    async def lockdown(self, ctx, textchannel: typing.Optional[discord.TextChannel], *, reason=None):

        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return

        if not textchannel:
            await ctx.message.delete()
            textchannel = ctx.channel
        else:
            await ctx.message.add_reaction('🔓')

        perms = textchannel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = False

        if reason:
            await textchannel.set_permissions(ctx.guild.default_role, overwrite=perms,
                                              reason=f'locked by {ctx.author} - {reason}')
            embed = discord.Embed(
                description=f"{ctx.author.mention} has locked down {textchannel.mention} \n```reason: {reason}```",
                color=ctx.me.color)
        else:
            await textchannel.set_permissions(ctx.guild.default_role, overwrite=perms, reason=f'locked by {ctx.author}')
            embed = discord.Embed(description=f"{ctx.author.mention} has locked down {textchannel.mention}",
                                  color=ctx.me.color)
        await textchannel.send(embed=embed)

    # -------------------------------------------------------------#
    # ------------------------ UNLOCK -----------------------------#
    # -------------------------------------------------------------#

    @lockdown.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure): await self.perms_error(ctx)

    @commands.command(aliases=['unlock', 'uld'])
    @commands.has_permissions(manage_channels=True)
    async def unlockdown(self, ctx, textchannel: typing.Optional[discord.TextChannel], *, reason=None):

        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return

        if not textchannel:
            await ctx.message.delete()
            textchannel = ctx.channel
        else:
            await ctx.message.add_reaction('🔓')

        perms = textchannel.overwrites_for(ctx.guild.default_role)
        perms.send_messages = True

        if reason:
            await textchannel.set_permissions(ctx.guild.default_role, overwrite=perms,
                                              reason=f'unlocked by {ctx.author} - {reason}')
            embed = discord.Embed(
                description=f"{ctx.author.mention} has unlocked {textchannel.mention} \n```reason: {reason}```",
                color=ctx.me.color)
        else:
            await textchannel.set_permissions(ctx.guild.default_role, overwrite=perms,
                                              reason=f'unlocked by {ctx.author}')
            embed = discord.Embed(description=f"{ctx.author.mention} has unlocked {textchannel.mention}",
                                  color=ctx.me.color)
        await textchannel.send(embed=embed)

    @unlockdown.error
    async def clear_error(self, ctx, error):
        if isinstance(error, commands.CheckFailure): await self.perms_error(ctx)

    # --------------------------------------------------------------------#
    # ------------------------ MOVE MESSAGES -----------------------------#
    # --------------------------------------------------------------------#

    @commands.command()
    async def move(self, ctx, amount: typing.Optional[int], channel: typing.Optional[discord.TextChannel]):
        if not any(role in self.staff_roles for role in ctx.author.roles):
            await self.perms_error(ctx)
            return

        # Limitation checking

        if channel == None:
            await self.error_message(ctx, 'you must specify a channel: .move <amount> <#channel>')
            ctx.command.reset_cooldown(ctx)
            return
        elif channel == ctx.channel:
            await self.error_message(ctx, "channel can't be this channel: .move <amount> <#channel>")
            ctx.command.reset_cooldown(ctx)
            return
        if not channel.permissions_for(ctx.guild.me).manage_webhooks and not ctx.channel.permissions_for(
                ctx.me).manage_messages:
            await self.error_message(ctx, 'missing necessary permissions')
            ctx.command.reset_cooldown(ctx)
            return
        if amount == None:
            await self.error_message(ctx, 'you must specify an amount: .move <amount> <#channel>')
            ctx.command.reset_cooldown(ctx)
            return
        elif amount > 20:
            await self.error_message(ctx, 'you can only move 15 messages!')
            ctx.command.reset_cooldown(ctx)
        else:
            try:
                await ctx.message.delete()
            except:
                await ctx.send('missing manage_messages permission', delete_after=5)
                ctx.command.reset_cooldown(ctx)
                return

        # Actual copying and pasting

        history = []
        async for message in ctx.channel.history(limit=amount):
            history.append(message)
            await asyncio.sleep(0.001)
        history.reverse()

        try:
            webhook = await channel.create_webhook(name="DB-Move", reason="created webhook for move command")
        except:
            await ctx.send(f"i'm missing manage_webhooks permission in {channel.mention}", delete_after=5)
            ctx.command.reset_cooldown(ctx)
            return

        for message in history:
            if message.attachments:
                file = ctx.message.attachments[0]
                myfile = await file.to_file()
                if message.embeds:
                    embed = message.embeds[0]
                    await webhook.send(username=message.author.display_name,
                                       avatar_url=message.author.display_avatar.url, file=myfile,
                                       content=message.content, embed=embed)
                else:
                    await webhook.send(username=message.author.display_name,
                                       avatar_url=message.author.display_avatar.url, file=myfile,
                                       content=message.content)
            else:
                if message.embeds:
                    embed = message.embeds[0]
                    await webhook.send(username=message.author.display_name,
                                       avatar_url=message.author.display_avatar.url, content=message.content,
                                       embed=embed)
                else:
                    await webhook.send(username=message.author.display_name,
                                       avatar_url=message.author.display_avatar.url, content=message.content)
            try:
                await message.delete()
            except:
                pass
            await asyncio.sleep(0.5)

        await webhook.delete()
        await ctx.send(f'moved {amount} messages to {channel.mention}')

    # ------------------------------------------------------------------------------#
    # --------------------------------- UNBAN --------------------------------------#
    # ------------------------------------------------------------------------------#

    @commands.command(help="unbans a member # run without arguments to get a list of entries", usage="[entry]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, ban_members=True)
    @commands.cooldown(1, 3.0, commands.BucketType.user)
    async def unban(self, ctx, number: typing.Optional[int]):
        if not ctx.channel.permissions_for(ctx.me).ban_members:
            await ctx.send("i'm missing the ban_members permission :pensive:")
            return
        if not number:
            try:
                bans = await ctx.guild.bans()
            except:
                await ctx.send("i'm missing the ban_members permission :pensive:")
                return
            if not bans:
                await ctx.send(embed=discord.Embed(title="There are no banned users in this server"))
                return
            desc = []
            number = 1
            for ban_entry in bans:
                desc.append(f"**{number}) {ban_entry.user}**")
                number = number + 1
            pages = menus.MenuPages(source=BanEmbed(desc), clear_reactions_after=True)
            await pages.start(ctx)
            return

        if number <= 0:
            embed = discord.Embed(color=0xFF0000,
                                  description=f"__number__ must be greater than 1\nsyntax: `{ctx.prefix}{ctx.command} {ctx.command.usage}`\n To get the number use the `{ctx.prefix}{ctx.command}` command")
            await ctx.send(embed=embed)
            return

        number = number - 1

        try:
            bans = await ctx.guild.bans()
        except:
            await ctx.send("i'm missing the ban_members permission :pensive:")
            return
        if not bans:
            await ctx.send(embed=discord.Embed(title="There are no banned users in this server"))
            return

        try:
            ban_entry = bans[number]
        except:
            embed = discord.Embed(color=0xFF0000,
                                  description=f"That member was not found. \nsyntax: `{ctx.prefix}{ctx.command} {ctx.command.usage}`\n To get the number use the `{ctx.prefix}{ctx.command}` command")
            await ctx.send(embed=embed)
            return

        confirm = await Confirm(f'are you sure you want to unban {ban_entry.user}?').prompt(ctx)
        if confirm:
            await ctx.guild.unban(ban_entry.user)
            await ctx.send(f'unbanned {ban_entry.user}')
        else:
            await ctx.send('cancelled!')

    # ------------------------------------------------------------------------------#
    # -------------------------------- BAN LIST ------------------------------------#
    # ------------------------------------------------------------------------------#

    @commands.command(help="Gets a list of bans in the server")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, ban_members=True)
    @commands.cooldown(1, 3.0, commands.BucketType.user)
    async def bans(self, ctx):
        try:
            bans = await ctx.guild.bans()
        except:
            await ctx.send("i'm missing the ban_members permission :pensive:")
            return
        if not bans:
            await ctx.send(embed=discord.Embed(title="There are no banned users in this server"))
            return
        desc = []
        number = 1
        for ban_entry in bans:
            desc.append(f"**{number}) {ban_entry.user}**")
            number = number + 1
        pages = menus.MenuPages(source=BanEmbed(desc), clear_reactions_after=True)
        await pages.start(ctx)

    # ------------------------------------------------------------------------------#
    # -------------------------------- BAN INFO ------------------------------------#
    # ------------------------------------------------------------------------------#

    @commands.command(help="brings info about a ban # run without arguments to get a list of entries", usage="[entry]")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(send_messages=True, embed_links=True, ban_members=True)
    @commands.cooldown(1, 3.0, commands.BucketType.user)
    async def baninfo(self, ctx, number: typing.Optional[int]):
        if not ctx.channel.permissions_for(ctx.me).ban_members:
            await ctx.send("i'm missing the ban_members permission :pensive:")
            return
        if not number:
            try:
                bans = await ctx.guild.bans()
            except:
                await ctx.send("i'm missing the ban_members permission :pensive:")
                return
            if not bans:
                await ctx.send(embed=discord.Embed(title="There are no banned users in this server"))
                return

            desc = []
            number = 1
            for ban_entry in bans:
                desc.append(f"**{number}) {ban_entry.user}**")
                number = number + 1
            pages = menus.MenuPages(source=BanEmbed(desc), clear_reactions_after=True)
            await pages.start(ctx)
            return

        if number <= 0:
            embed = discord.Embed(color=0xFF0000,
                                  description=f"__number__ must be greater than 1\nsyntax: `{ctx.prefix}{ctx.command} {ctx.command.usage}`\n To get the number use the `{ctx.prefix}{ctx.command}` command")
            await ctx.send(embed=embed)
            return

        number = number - 1

        try:
            bans = await ctx.guild.bans()
        except:
            await ctx.send("i'm missing the ban_members permission :pensive:")
            return
        if not bans:
            await ctx.send(embed=discord.Embed(title="There are no banned users in this server"))
            return
        try:
            ban_entry = bans[number]
        except:
            embed = discord.Embed(color=0xFF0000,
                                  description=f"That member was not found. \nsyntax: `{ctx.prefix}{ctx.command} "
                                              f"{ctx.command.usage}`\n To get the number use the `{ctx.prefix}"
                                              f"{ctx.command}` command")
            await ctx.send(embed=embed)
            return

        date = ban_entry.user.created_at
        embed = discord.Embed(color=ctx.me.color,
                              description=f"""```yaml
       user: {ban_entry.user}
    user id: {ban_entry.user.id}
     reason: {ban_entry.reason}
 created at: {date.strftime("%b %-d %Y at %-H:%M")} UTC
```""")
        embed.set_author(name=ban_entry.user, icon_url=ban_entry.user.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.group()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def massban(self, ctx, *, args):
        """Mass-bans members from the server.
        do ""%PRE%help massban help" for help"""
        # For some reason there are cases due to caching that ctx.author
        # can be a User even in a guild only context
        # Rather than trying to work out the kink with it
        # Just upgrade the member itself.
        if not isinstance(ctx.author, discord.Member):
            try:
                author = await ctx.guild.fetch_member(ctx.author.id)
            except discord.HTTPException:
                return await ctx.send('Somehow, Discord does not seem to think you are in this server.')
        else:
            author = ctx.author

        parser = Arguments(add_help=False, allow_abbrev=False)
        parser.add_argument('--channel', '-c')
        parser.add_argument('--reason', '-r')
        parser.add_argument('--search', type=int, default=100)
        parser.add_argument('--regex')
        parser.add_argument('--no-avatar', action='store_true')
        parser.add_argument('--no-roles', action='store_true')
        parser.add_argument('--created', type=int)
        parser.add_argument('--joined', type=int)
        parser.add_argument('--joined-before', type=int)
        parser.add_argument('--joined-after', type=int)
        parser.add_argument('--contains')
        parser.add_argument('--starts')
        parser.add_argument('--ends')
        parser.add_argument('--match')
        parser.add_argument('--show', action='store_true')
        parser.add_argument('--embeds', action='store_const', const=lambda m: len(m.embeds))
        parser.add_argument('--files', action='store_const', const=lambda m: len(m.attachments))
        parser.add_argument('--after', type=int)
        parser.add_argument('--before', type=int)

        try:
            args = parser.parse_args(shlex.split(args))
        except Exception as e:
            return await ctx.send(str(e))

        members = []

        if args.channel:
            channel = await commands.TextChannelConverter().convert(ctx, args.channel)
            before = args.before and discord.Object(id=args.before)
            after = args.after and discord.Object(id=args.after)
            predicates = []
            if args.contains:
                predicates.append(lambda m: args.contains in m.content)
            if args.starts:
                predicates.append(lambda m: m.content.startswith(args.starts))
            if args.ends:
                predicates.append(lambda m: m.content.endswith(args.ends))
            if args.match:
                try:
                    _match = re.compile(args.match)
                except re.error as e:
                    return await ctx.send(f'Invalid regex passed to `--match`: {e}')
                else:
                    predicates.append(lambda m, x=_match: x.match(m.content))
            if args.embeds:
                predicates.append(args.embeds)
            if args.files:
                predicates.append(args.files)

            async for message in channel.history(limit=min(max(1, args.search), 2000), before=before, after=after):
                if all(p(message) for p in predicates):
                    members.append(message.author)
        else:
            if ctx.guild.chunked:
                members = ctx.guild.members
            else:
                async with ctx.typing():
                    await ctx.guild.chunk(cache=True)
                members = ctx.guild.members

        # member filters
        predicates = [
            lambda m: isinstance(m, discord.Member) and can_execute_action(ctx, author, m),  # Only if applicable
            lambda m: not m.bot,  # No bots
            lambda m: m.discriminator != '0000',  # No deleted users
        ]

        converter = commands.MemberConverter()

        if args.regex:
            try:
                _regex = re.compile(args.regex)
            except re.error as e:
                return await ctx.send(f'Invalid regex passed to `--regex`: {e}')
            else:
                predicates.append(lambda m, x=_regex: x.match(m.name))

        if args.no_avatar:
            predicates.append(lambda m: m.avatar == m.default_avatar)
        if args.no_roles:
            predicates.append(lambda m: len(getattr(m, 'roles', [])) <= 1)

        now = discord.utils.utcnow()
        if args.created:
            def created(member, *, offset=now - datetime.timedelta(minutes=args.created)):
                return member.created_at > offset

            predicates.append(created)
        if args.joined:
            def joined(member, *, offset=now - datetime.timedelta(minutes=args.joined)):
                if isinstance(member, discord.User):
                    # If the member is a user then they left already
                    return True
                return member.joined_at and member.joined_at > offset

            predicates.append(joined)
        if args.joined_after:
            _joined_after_member = await converter.convert(ctx, str(args.joined_after))

            def joined_after(member, *, _other=_joined_after_member):
                return member.joined_at and _other.joined_at and member.joined_at > _other.joined_at

            predicates.append(joined_after)
        if args.joined_before:
            _joined_before_member = await converter.convert(ctx, str(args.joined_before))

            def joined_before(member, *, _other=_joined_before_member):
                return member.joined_at and _other.joined_at and member.joined_at < _other.joined_at

            predicates.append(joined_before)

        members = {m for m in members if all(p(m) for p in predicates)}
        if len(members) == 0:
            return await ctx.send('No members found matching criteria.')

        if args.show:
            members = sorted(members, key=lambda m: m.joined_at or now)
            fmt = "\n".join(f'{m.id}\tJoined: {m.joined_at}\tCreated: {m.created_at}\t{m}' for m in members)
            content = f'Current Time: {discord.utils.utcnow()}\nTotal members: {len(members)}\n{fmt}'
            file = discord.File(io.BytesIO(content.encode('utf-8')), filename='members.txt')
            return await ctx.send(file=file)

        if args.reason is None:
            return await ctx.send('--reason flag is required.')
        else:
            reason = await ActionReason().convert(ctx, args.reason)

        confirm = await ctx.prompt(f'This will ban **{len(members)} member(s)**. Are you sure?')
        if not confirm:
            return await ctx.send('Aborting.')

        count = 0
        for member in members:
            try:
                await ctx.guild.ban(member, reason=reason)
            except discord.HTTPException:
                pass
            else:
                count += 1

        await ctx.send(f'Banned {count}/{len(members)}')

    @massban.command(name="help")
    async def _help(self, ctx):
        """Mass bans multiple members from the server.
        This command has a powerful "command line" syntax. To use this command
        you and the bot must both have Ban Members permission. **Every option is optional.**
        Users are only banned **if and only if** all conditions are met.
        The following options are valid.
        --channel / -c: Channel to search for message history.
        --reason / -r: The reason for the ban.
        --regex: Regex that usernames must match.
        --created: Matches users whose accounts were created less than specified minutes ago.
        --joined: Matches users that joined less than specified minutes ago.
        --joined-before: Matches users who joined before the member ID given.
        --joined-after: Matches users who joined after the member ID given.
        --no-avatar: Matches users who have no avatar. (no arguments)
        --no-roles: Matches users that have no role. (no arguments)
        --show: Show members instead of banning them (no arguments).
        Message history filters (Requires --channel):
        --contains: A substring to search for in the message.
        --starts: A substring to search if the message starts with.
        --ends: A substring to search if the message ends with.
        --match: A regex to match the message content to.
        --search: How many messages to search. Default 100. Max 2000.
        --after: Messages must come after this message ID.
        --before: Messages must come before this message ID.
        --files: Checks if the message has attachments (no arguments).
        --embeds: Checks if the message has embeds (no arguments).
        """
        return

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def softban(self, ctx: commands.Context, member: discord.User, *, reason: ActionReason = None):
        """Soft bans a member from the server.
        A softban is basically banning the member from the server but
        then unbanning the member as well. This allows you to essentially
        kick the member while removing their messages.
        """

        if reason is None:
            reason = f'Action done by {ctx.author} (ID: {ctx.author.id})'

        await ctx.guild.ban(member, reason=reason)
        await ctx.guild.unban(member, reason=reason)
        await ctx.send('\N{OK HAND SIGN}')


def setup(bot):
    bot.add_cog(Moderation(bot))
