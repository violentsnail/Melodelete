import discord
import discord.ext.commands as commands
import json
import asyncio
import aiohttp
import os
from datetime import datetime, timedelta, timezone
import logging

import config

from typing import Optional

# Configure logging
log_filename = "melodelete.log"
log_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), log_filename)

logger = logging.getLogger("melodelete")

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(name)-15s %(levelname)-8s %(message)s',
                    handlers=[
                        logging.FileHandler(log_filepath),
                        logging.StreamHandler()
                    ])

# Load the configuration
config = config.Config()

# Create a Discord client
intents = discord.Intents.default()
intents.messages = True
intents.reactions = False
intents.typing = False

# Set up an HTTP request tracer that will let us know what the current rate
# limit is for deletions.

async def on_request_end(session, trace_config_ctx, params):
    if (params.method == "DELETE"  # Message deletions use the DELETE HTTP method
     or params.url.path.endswith("/bulk-delete")):  # Bulk Delete Messages POSTs here
        try:
            if int(params.response.headers["X-RateLimit-Remaining"]) == 0:
                # We have hit the limit and can therefore define it.
                # The time to reset is assumed to apply equally to every
                # request before this one.
                rate_limit = float(params.response.headers["X-RateLimit-Reset-After"]) / int(params.response.headers["X-RateLimit-Limit"])
                config.set_rate_limit(rate_limit)
                logger.info(f"Rate limit is now {rate_limit} seconds")
        except ValueError:
            logger.warn(f"Rate-limiting header values malformed (X-RateLimit-Reset-After: {params.response.headers['X-RateLimit-Reset-After']}; X-RateLimit-Limit: {params.response.headers['X-RateLimit-Limit']}; X-RateLimit-Remaining: {params.response.headers['X-RateLimit-Remaining']})")
        except KeyError:
            logger.warn("No rate-limiting headers received in response to DELETE")
        except ZeroDivisionError:
            logger.warn("Rate-limiting headers suggest that we cannot make any requests")

trace_config = aiohttp.TraceConfig()
trace_config.on_request_end.append(on_request_end)

client = commands.Bot(commands.when_mentioned, intents=intents, http_trace=trace_config)

"""Scans the given channel for messages that can be deleted in the given channel
   given the current configuration and returns a sequence of those messages.

   In:
     channel: The discord.TextChannel instance to scan for deletable messages.
     time_threshold: The number of minutes of history before which messages are
       deletable, or None if this is not to be used as a criterion.
     max_messages: The maximum number of messages to leave in the channel, or
       None if this is not to be used as a criterion.
   Returns:
     A sequence of discord.Message objects that represent deletable messages."""
async def get_channel_deletable_messages(channel, time_threshold, max_messages):
    messages = []  # fallback if no criteria
    if time_threshold is not None:  # and max_messages is to be determined
        time_cutoff = datetime.now(timezone.utc) - timedelta(minutes=time_threshold)
        if max_messages:  # if both criteria
            messages = [message async for message in channel.history(limit=None, oldest_first=True) if not message.pinned]
            messages = [message for i, message in enumerate(messages) if i < len(messages) - max_messages or message.created_at < time_cutoff]
        else:  # and max_messages is None
            messages = [message async for message in channel.history(limit=None, before=time_cutoff, oldest_first=True) if not message.pinned]
    elif max_messages is not None:  # and time_threshold is None
        messages = [message async for message in channel.history(limit=None, oldest_first=True) if not message.pinned][:-max_messages]

    return messages

"""Deletes the given messages from the channel that contains them using a single
   Bulk Delete Messages call if possible, falling back to single deletions if it
   fails.

   In:
     messages: A sequence of discord.Message objects representing the messages
       to be deleted. They must all belong to the same channel."""
async def delete_messages(messages):
    if len(messages) > 100:
        messages = list(messages)  # Only index on a proper list
        for i in range(0, len(messages), 100):
            await delete_messages(messages[i : i+100])
    elif len(messages):
        channel = messages[0].channel
        try:
            await asyncio.sleep(config.get_rate_limit())
            await channel.delete_messages(messages)
        except discord.NotFound as e:  # only if it resolves to a single message
            logger.info("Message ID {messages[0].id} in #{channel.name} (ID: {channel.id}) was deleted since scanning")
        except discord.ClientException as e:
            logger.exception("Failed to bulk delete {len(messages)} messages in #{channel.name} (ID: {channel.id}) due to the API considering the count to be too large; falling back to individual deletions", exc_info=e)
            for message in messages:
                await delete_message(message)
        except discord.HTTPException as e:
            logger.info("Failed to bulk delete {len(messages)} messages in #{channel.name} (ID: {channel.id}); falling back to individual deletions", exc_info=e)
            for message in messages:
                await delete_message(message)

"""Deletes the given message from the channel that contains it.

   In:
     message: A discord.Message object representing the message to be deleted."""
async def delete_message(message):
    try:
        await asyncio.sleep(config.get_rate_limit())
        await message.delete()
    except discord.NotFound as e:
        logger.info("Message ID {message.id} in #{message.channel.name} (ID: {message.channel.id}) was deleted since scanning")
    except discord.HTTPException as e:
        logger.exception("Failed to delete message ID {message.id} in #{message.channel.name} (ID: {message.channel.id})", exc_info=e)

"""Deletes the given sequence of messages, which must all be part of the same
   channel, balancing using the fewest possible API calls with polluting the
   Audit Log as little as possible.

   In:
     messages: The list of messages to delete."""
async def delete_channel_deletable_messages(messages):
    if len(messages) >= config.get_bulk_delete_min():
        # The Bulk Delete Messages API call only supports deleting messages
        # up to 14 days ago:
        # https://discord.com/developers/docs/resources/channel#bulk-delete-messages
        # (Why? https://github.com/discord/discord-api-docs/issues/208)
        time_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        batch = []  # The batch of messages we are accumulating for Bulk Delete

        for message in messages:
            if message.created_at < time_cutoff:  # too old; delete single
                await delete_message(message)
            else:  # add to the batch
                batch.append(message)
                if len(batch) == 100:
                    await delete_messages(batch)
                    batch = []

        if len(batch):
            await delete_messages(batch)
    else:
        for message in messages:
            await delete_message(message)

"""Deletes deletable messages from all configured channels."""
async def delete_old_messages():
    config.set_rate_limit(0)

    to_delete = []  # List of tuples of (Channel, List[Message])

    for channel_config in config.get_channels():
        channel_id = channel_config["id"]
        time_threshold = channel_config.get("time_threshold", None)
        max_messages = channel_config.get("max_messages", None)
        channel = client.get_channel(channel_id)
        if channel:
            try:
                deletable_messages = await get_channel_deletable_messages(channel, time_threshold=time_threshold, max_messages=max_messages)
                logger.info(f"#{channel.name} (ID: {channel_id}) has {len(deletable_messages)} messages to delete.")
                to_delete.append((channel, deletable_messages))
            except Exception as e:
                logger.exception(f"Failed to scan for messages to delete in #{channel.name} (ID: {channel_id})", exc_info=e)
        else:
            logger.error(f"Channel not found: {channel_id}")

    for channel, deletable_messages in to_delete:
        try:
            await delete_channel_deletable_messages(deletable_messages)
        except Exception as e:
            logger.exception(f"Failed to delete messages in #{channel.name} (ID: {channel.id})", exc_info=e)

# Since on_ready may be called more than once during a bot session, we need to
# make sure our main loop is only run once.
# See <https://discordpy.readthedocs.io/en/stable/api.html#discord.on_ready>
# This function is not guaranteed to be the first event called. Likewise, this
# function is *not* guaranteed to only be called once. This library implements
# reconnection logic and thus will end up calling this event whenever a RESUME
# request fails.
main_loop_started = False

@client.event
async def on_ready():
    logger.info(f"Logged in as {client.user.name}#{client.user.discriminator} (ID: {client.user.id})")

    # Only start this loop once.
    global main_loop_started
    if main_loop_started:
        return

    main_loop_started = True

    while True:
        logger.info("-- New scan --")
        await delete_old_messages()
        await asyncio.sleep(120)  # Wait 2 minutes before running through again

def allowed_roles_only():
    return commands.has_any_role(*config.get_allowed_role_names())

@client.command()
@allowed_roles_only()
async def ping(context: commands.context.Context):
    """Sends a reply saying whether you have permission to run commands.

       If no message is sent, the bot is down or reconnecting to the server."""
    async with context.typing():
        await context.reply("Hi there! You have permission to use commands.")

@client.command()
@allowed_roles_only()
async def clear(context: commands.context.Context,
                channel: Optional[discord.TextChannel] = commands.parameter(default=lambda ctx: ctx.channel, description="The channel to be removed from auto-delete.", displayed_default="<this channel>")):
    """Removes a channel from auto-delete."""
    async with context.typing():
        config.clear_channel(channel.id)
        await channel.send("This channel has been removed from auto-delete.")
        if context.channel != channel:
            await context.reply(f"{channel.mention} has been removed from auto-delete. A message was sent to the channel to let its users know of the change.")

class ConfigFlags(commands.FlagConverter, delimiter='', prefix='-'):
    h:   Optional[int] = commands.flag(description="Number of hours of recent messages to leave in the channel")
    max: Optional[int] = commands.flag(description="Maximum number of recent messages to leave in the channel")

@client.command(name="config")  # The package config is already in scope
@allowed_roles_only()
async def configure(context: commands.context.Context,
                    channel: Optional[discord.TextChannel] = commands.parameter(default=lambda ctx: ctx.channel, description="The channel whose configuration is to be retrieved or set.", displayed_default="<this channel>"),
                 *, flags: ConfigFlags = commands.parameter(description="See Flags.")):
    """Retrieves or sets a channel's auto-delete configuration.

       If at least one of the flags is provided, the channel's
       auto-delete configuration is set; otherwise, it is retrieved.

       Flags:
         [-h<#>]    Number of hours of recent messages to leave in the channel
         [-max<#>]  Maximum number of recent messages to leave in the channel"""
    async with context.typing():
        hours, max_messages = flags.h, flags.max
        if hours is None and max_messages is None:
            for channel_config in config.get_channels():
                if channel.id == channel_config["id"]:
                    time_threshold_hours = f"{channel_config['time_threshold'] // 60} hours" if "time_threshold" in channel_config and channel_config["time_threshold"] is not None else "Not set"
                    max_messages = channel_config["max_messages"] if "max_messages" in channel_config and channel_config["max_messages"] is not None else "Not set"
                    await context.send(f"Current settings for {channel.mention}:\n- Time threshold: {time_threshold_hours}\n- Max messages: {max_messages}")
                    break
            else:  # channel not found
                await context.send(f"{channel.mention} is not configured for auto-delete.")
        else:
            time_threshold = hours
            if time_threshold is not None:
                time_threshold *= 60  # Convert hours to minutes

            config.set_channel(channel.id, time_threshold=time_threshold, max_messages=max_messages)

            # Send to the TARGET channel to let its users know of the change.
            if hours is not None and max_messages is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted, and there will be a maximum of {max_messages} messages.")
            elif hours is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted.")
            elif max_messages is not None:
                await channel.send(f"Auto-delete settings for this channel have been updated: there will be a maximum of {max_messages} messages.")
            # Then, if the channel the command was issued in is not the target
            # channel, drop something in the channel the command was issued in
            # to let the bot master know that the command succeeded.
            if context.channel != channel:
                await context.reply(f"Auto-delete settings for {channel.mention} have been updated. A message was sent to the channel to let its users know of the setting change.")

@client.event
async def on_command_error(context: commands.context.Context, error: commands.CommandError):
    if isinstance(error, commands.MissingAnyRole):
        await context.reply("You don't have permission to use this command.")
    elif isinstance(error, commands.BadArgument):
        await context.reply(f"An invalid value was encountered while processing this command: {error}" if str(error) else "An invalid value was encountered while processing this command.")
    elif not isinstance(error, commands.CommandNotFound):
        raise error

@client.event
async def on_raw_message_delete(payload):
    channels = config.get_channels()
    channel = client.get_channel(payload.channel_id)

    if channel and payload.channel_id in [channel["id"] for channel in channels]:
        logger.info(f"Message deleted in #{channel.name} (ID: {payload.channel_id})")

@client.event
async def on_raw_bulk_message_delete(payload):
    channels = config.get_channels()
    channel = client.get_channel(payload.channel_id)

    if channel and payload.channel_id in [channel["id"] for channel in channels]:
        logger.info(f"{len(payload.message_ids)} messages deleted in #{channel.name} (ID: {payload.channel_id})")

# Run the bot
client.run(config.get_token(), log_handler=None)
