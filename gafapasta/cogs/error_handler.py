
import io
import traceback
import logging
import  discord, asyncio
from discord.ext import commands
from discord.ext.commands import BucketType

class handler(commands.Cog):
    """🆘 manejar los errores 👀"""
    def __init__(self, bot):
        self.bot = bot
        self.error_channel = 880181130408636456

    @commands.Cog.listener('on_command_error')
    async def error_handler(self, ctx: commands.Context, error):
        error = getattr(error, "original", error)
        ignored = (
            commands.CommandNotFound,
        )
        if isinstance(error, ignored):
            return

        if isinstance(error, discord.ext.commands.CheckAnyFailure):
            for e in error.errors:
                if not isinstance(error, commands.NotOwner):
                    error = e
                    break

        if isinstance(error, discord.ext.commands.BadUnionArgument):
            if error.errors:
                error = error.errors[0]

        embed = discord.Embed(color=0xD7342A)
        embed.set_author(name='Missing permissions!',
                         icon_url='https://i.imgur.com/OAmzSGF.png')

        if isinstance(error, commands.NotOwner):
            return await ctx.send(f"you must own `{ctx.me.display_name}` to use `{ctx.command}`")

        if isinstance(error, commands.TooManyArguments):
            return await ctx.send(f"Too many arguments passed to the command!")

        if isinstance(error, discord.ext.commands.MissingPermissions):
            text = f"You're missing the following permissions: \n**{', '.join(error.missing_permissions)}**"
            embed.description = text
            try:
                return await ctx.send(embed=embed)
            except discord.Forbidden:
                try:
                    return await ctx.send(text)
                except discord.Forbidden:
                    pass
                finally:
                    return

        if isinstance(error, discord.ext.commands.BotMissingPermissions):
            text = f"I'm missing the following permissions: \n**{', '.join(error.missing_permissions)}**"
            try:
                embed.description = text
                await ctx.send(embed=embed)
            except discord.Forbidden:
                await ctx.send(text)
            finally:
                return

        elif isinstance(error, discord.ext.commands.MissingRequiredArgument):
            missing = f"{str(error.param).split(':')[0]}"
            command = f"{ctx.clean_prefix}{ctx.command} {ctx.command.signature}"
            separator = (' ' * (len(command.split(missing)[0]) - 1))
            indicator = ('^' * (len(missing) + 2))

            logging.info(f"`{separator}`  `{indicator}`")
            logging.info(error.param)

            return await ctx.send(
                f"```{command}\n{separator}{indicator}\n{missing} is a required argument that is missing.\n```")

        elif isinstance(error, commands.errors.PartialEmojiConversionFailure):
            return await ctx.send(f"`{error.argument}` is not a valid Custom Emoji")

        elif isinstance(error, commands.errors.CommandOnCooldown):
            embed = discord.Embed(color=0xD7342A,
                                  description=f'Please try again in {round(error.retry_after, 2)} seconds')
            embed.set_author(name='Command is on cooldown!',
                             icon_url='https://i.imgur.com/izRBtg9.png')

            if error.type == BucketType.default:
                per = ""
            elif error.type == BucketType.user:
                per = "per user"
            elif error.type == BucketType.guild:
                per = "per server"
            elif error.type == BucketType.channel:
                per = "per channel"
            elif error.type == BucketType.member:
                per = "per member"
            elif error.type == BucketType.category:
                per = "per category"
            elif error.type == BucketType.role:
                per = "per role"
            else:
                per = ""

            embed.set_footer(
                text=f"cooldown: {error.cooldown.rate} per {error.cooldown.per}s {per}")
            return await ctx.send(embed=embed)

        elif isinstance(error, commands.errors.MemberNotFound):
            return await ctx.send(f"I couldn't find `{error.argument}` in this server")

        elif isinstance(error, commands.errors.UserNotFound):
            return await ctx.send(
                f"I've searched far and wide, but `{error.argument}` doesn't seem to be a member discord user...")

        elif isinstance(error, commands.BadArgument):
            return await ctx.send(error or "Bad argument given!")

        elif isinstance(error, discord.HTTPException):
            await ctx.send("Oh no! An unexpected HTTP error occurred while handling this command! 😔"
                           "\nI've notified the developers about it. in the meantime, maybe try again?")

        elif isinstance(error, discord.Forbidden):
            await ctx.send("Oh no! It seems like I don't have permissions to perform that action!"
                           "\nThis may be due to me missing permissions in a specific channel, server"
                           "permissions, or an issue with role hierarchy. Try adjusting my permissions"
                           "for this server. \n(Note that I can't edit the server owner)")

        error_channel = self.bot.get_channel(self.error_channel)

        traceback_string = "".join(traceback.format_exception(
            etype=None, value=error, tb=error.__traceback__))

        await self.bot.wait_until_ready()

        await ctx.send(f"""```diff\n- Un error inesperado ha ocurrido durante la ejecución del comando \"{ctx.command}\"
{error}```""")

        if ctx.me.guild_permissions.administrator:
            admin = '✅'
        else:
            admin = '❌'

        if ctx.guild:
            command_data = f"command: {ctx.message.content[0:1700]}" \
                           f"\nguild_id: {ctx.guild.id}" \
                           f"\nowner_id: {ctx.guild.owner.id}" \
                           f"\nbot admin: {admin} " \
                           f"- role pos: {ctx.me.top_role.position}"
        else:
            command_data = f"command: {ctx.message.content[0:1700]}" \
                           f"\nCommand executed in DMs"

        to_send = f"```yaml\n{command_data}``````py\n{ctx.command} " \
                  f"command raised an error:\n{traceback_string}\n```"
        if len(to_send) < 2000:
            try:
                sent_error = await error_channel.send(to_send)

            except (discord.Forbidden, discord.HTTPException):
                sent_error = await error_channel.send(f"```yaml\n{command_data}``````py Command: {ctx.command}"
                                                      f"Raised the following error:\n```",
                                                      file=discord.File(io.StringIO(traceback_string),
                                                                        filename='traceback.py'))
        else:
            sent_error = await error_channel.send(f"```yaml\n{command_data}``````py Command: {ctx.command}"
                                                  f"Raised the following error:\n```",
                                                  file=discord.File(io.StringIO(traceback_string),
                                                                    filename='traceback.py'))
        try:
            await sent_error.add_reaction('🗑')
        except (discord.HTTPException, discord.Forbidden):
            pass
        raise error

def setup(bot):
    bot.add_cog(handler(bot))
