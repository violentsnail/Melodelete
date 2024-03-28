import discord
from discord import app_commands

from typing import Optional

def allowed_roles_only():
    def predicate(interaction: discord.Interaction):
        user_roles = [role.name for role in interaction.user.roles]
        access_roles = interaction.command.parent.config.get_allowed_role_names()
        if not any(role in user_roles for role in access_roles):
            raise app_commands.MissingAnyRole(access_roles)
        return True
    return app_commands.check(predicate)

@app_commands.guild_only()
class AutodeleteCommands(app_commands.Group):
    """Manage auto-delete settings (subcommand required)"""
    def __init__(self, bot, config, **kwargs):
        super().__init__(**kwargs)
        self.bot = bot
        self.config = config

    @app_commands.command()
    @app_commands.guild_only()
    async def ping(self, interaction: discord.Interaction) -> None:
        """Check if the auto-delete bot is up"""
        await interaction.response.send_message("Hi there! I am currently up.", ephemeral=True)

    @app_commands.command()
    @app_commands.guild_only()
    @app_commands.describe(channel="Channel to be removed from auto-delete (default: here)")
    @allowed_roles_only()
    async def clear(self, interaction: discord.Interaction,
                    channel: Optional[discord.TextChannel]) -> None:
        """Remove a channel from auto-delete"""
        if channel is None:
            channel = interaction.channel

        self.config.clear_channel(channel.id)
        # Send to the TARGET channel to let its users know of the change.
        await channel.send("This channel has been removed from auto-delete.")
        # Then respond to the command.
        if interaction.channel != channel:
            await interaction.response.send_message(f"Auto-delete settings for {channel.mention} have been updated. A message was sent to the channel to let its users know of the setting change.")
        else:
            await interaction.response.send_message("The command completed successfully.", ephemeral=True)

    @app_commands.command()
    @app_commands.guild_only()
    @app_commands.describe(channel="Channel whose settings are to be viewed or set (default: here)",
                           hours="Set the number of hours of recent messages to keep",
                           messages="Set the maximum number of recent messages to keep")
    @allowed_roles_only()
    async def config(self, interaction: discord.Interaction,
                     channel: Optional[discord.TextChannel], hours: Optional[int], messages: Optional[int]) -> None:
        """View or set a channel's auto-delete settings"""
        if channel is None:
            channel = interaction.channel

        if hours is None and messages is None:
            for channel_config in self.config.get_channels():
                if channel.id == channel_config["id"]:
                    time_threshold_hours = f"{channel_config['time_threshold'] // 60} hours" if "time_threshold" in channel_config and channel_config["time_threshold"] is not None else "Not set"
                    messages = channel_config["max_messages"] if "max_messages" in channel_config and channel_config["max_messages"] is not None else "Not set"
                    await interaction.response.send_message(f"Current settings for {channel.mention}:\n- Time threshold: {time_threshold_hours}\n- Max messages: {messages}")
                    break
            else:  # channel not found
                await interaction.response.send_message(f"{channel.mention} is not configured for auto-delete.")
        else:
            time_threshold = hours
            if time_threshold is not None:
                time_threshold *= 60  # Convert hours to minutes

            self.config.set_channel(channel.id, time_threshold=time_threshold, max_messages=messages)

            # Send to the TARGET channel to let its users know of the change.
            if hours is not None and messages is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted, and there will be a maximum of {messages} messages.")
            elif hours is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted.")
            elif messages is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: there will be a maximum of {messages} messages.")
            # Then respond to the command.
            if interaction.channel != channel:
                await interaction.response.send_message(f"Auto-delete settings for {channel.mention} have been updated. A message was sent to the channel to let its users know of the setting change.")
            else:
                await interaction.response.send_message("The command completed successfully.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingAnyRole):
            await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)
        elif isinstance(error, app_commands.TransformerError):
            await interaction.response.send_message(f"An invalid value was encountered while processing this command: {error}" if str(error) else "An invalid value was encountered while processing this command.", ephemeral=True)
        else:
            raise error
