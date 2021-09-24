import discord
import typing

from discord.ext import commands


class Confirm(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral message that we're confirming their choice.
    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.green)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.value = True
        self.stop()

    # This one is similar to the confirmation button except sets the inner value to `False`
    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.red)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        self.value = False
        self.stop()


class CustomContext(commands.Context):

    @staticmethod
    def tick(opt: bool, text: str = None) -> str:
        ticks = {
            True: '<:greenTick:596576670815879169>',
            False: '<:redTick:596576672149667840>',
            None: '<:greyTick:860644729933791283>',
        }
        emoji = ticks.get(opt, "<:redTick:596576672149667840>")
        if text:
            return f"{emoji} {text}"
        return emoji

    @staticmethod
    def default_tick(opt: bool, text: str = None) -> str:
        ticks = {
            True: '✅',
            False: '❌',
            None: '➖',
        }
        emoji = ticks.get(opt, "❌")
        if text:
            return f"{emoji} {text}"
        return emoji

    @staticmethod
    def square_tick(opt: bool, text: str = None) -> str:
        ticks = {
            True: '🟩',
            False: '🟥',
            None: '⬛',
        }
        emoji = ticks.get(opt, "🟥")
        if text:
            return f"{emoji} {text}"
        return emoji

    @staticmethod
    def dc_toggle(opt: bool, text: str = None) -> str:
        ticks = {
            True: '<:DiscordON:882991627541565461>',
            False: '<:DiscordOFF:882991627994542080>',
            None: '<:DiscordNONE:882991627994546237>',
        }
        emoji = ticks.get(opt, "<:DiscordOFF:882991627994542080>")
        if text:
            return f"{emoji} {text}"
        return emoji

    @staticmethod
    def toggle(opt: bool, text: str = None) -> str:
        ticks = {
            True: '<:toggle_on:857842924729270282>',
            False: '<:toggle_off:857842924544065536>',
            None: '<:toggle_off:857842924544065536>',
        }
        emoji = ticks.get(opt, "<:toggle_off:857842924544065536>")
        if text:
            return f"{emoji} {text}"
        return emoji

    async def send(self, content: str = None, embed: discord.Embed = None,
                   reply: bool = True, footer: bool = True,
                   reference: typing.Union[discord.Message, discord.MessageReference] = None, **kwargs):

        reference = (reference or self.message.reference or self.message) if reply is True else reference

        if embed and footer is True:
            if not embed.footer:
                embed.set_footer(text=f"Requested by {self.author}",
                                 icon_url=self.author.display_avatar.url)
                embed.timestamp = discord.utils.utcnow()

        if embed:
            embed.colour = embed.colour if embed.colour not in (discord.Color.default(), discord.Embed.Empty, None)\
                else self.me.color if self.me.color not in (discord.Color.default(), discord.Embed.Empty, None)\
                else self.author.color if self.author.color not in (discord.Color.default(), discord.Embed.Empty, None)\
                else discord.Color.blurple()

        try:
            return await super().send(content=content, embed=embed, reference=reference, **kwargs)
        except discord.HTTPException:
            return await super().send(content=content, embed=embed, reference=None, **kwargs)

    async def confirm(self, message: str = 'Do you want to confirm?', delete_after_confirm: int = False):
        view = Confirm()
        message = await self.send(message, view=view)
        await view.wait()
        if view.value is None:
            try:
                (await message.edit(view=None)) if \
                    delete_after_confirm is False else (await message.delete())
            except (discord.Forbidden, discord.HTTPException):
                pass
            return False
        elif view.value:
            try:
                (await message.edit(view=None)) if \
                    delete_after_confirm is False else (await message.delete())
            except (discord.Forbidden, discord.HTTPException):
                pass
            return True
        else:
            try:
                (await message.edit(view=None)) if \
                    delete_after_confirm is False else (await message.delete())
            except (discord.Forbidden, discord.HTTPException):
                pass
            return False
