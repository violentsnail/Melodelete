import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import time
import aiohttp
import os
from datetime import datetime, timedelta, timezone
import logging

import config
from melodelete_commands import AutodeleteCommands

from typing import Optional, Tuple, Sequence

logger = logging.getLogger("melodelete")

class Melodelete(commands.Bot):
    def __init__(self):
        # Load the configuration.
        self.config = config.Config()

        # Declare our intents, which are the things we want to know about as the
        # bot runs.
        intents = discord.Intents(guilds=True, guild_messages=True)

        # Set up an HTTP request tracer that will let us know what the current
        # rate limit is for deletions.
        trace_config = aiohttp.TraceConfig()
        trace_config.on_request_end.append(self._on_request_end)

        # Since on_ready may be called more than once during a bot session, we need to
        # make sure our main loop is only run once.
        # See <https://discordpy.readthedocs.io/en/stable/api.html#discord.on_ready>
        # This function is not guaranteed to be the first event called. Likewise, this
        # function is *not* guaranteed to only be called once. This library implements
        # reconnection logic and thus will end up calling this event whenever a RESUME
        # request fails.
        self.started = False

        super().__init__(commands.when_mentioned, intents=intents, help_command=None, http_trace=trace_config)

    def run(self, token: str = None, **kwargs) -> None:
        super().run(token if token is not None else self.config.get_token(), **kwargs)

    async def start(self, token: str = None, **kwargs) -> None:
        await super().start(token if token is not None else self.config.get_token(), **kwargs)

    async def login(self, token: str = None) -> None:
        await super().login(token if token is not None else self.config.get_token())

    async def _on_request_end(self, session: aiohttp.ClientSession, trace_config_ctx, params: aiohttp.TraceRequestEndParams) -> None:
        """Updates the rate limit based on an HTTP request that just ended."""
        if (params.method == "DELETE"  # Message deletions use the DELETE HTTP method
         or params.url.path.endswith("/bulk-delete")):  # Bulk Delete Messages POSTs here
            try:
                if int(params.response.headers["X-RateLimit-Remaining"]) == 0:
                    # We have hit the limit and can therefore define it.
                    # The time to reset is assumed to apply equally to every
                    # request before this one.
                    rate_limit = float(params.response.headers["X-RateLimit-Reset-After"]) / int(params.response.headers["X-RateLimit-Limit"])
                    self.config.set_rate_limit(rate_limit)
                    logger.info(f"Rate limit is now {rate_limit} seconds")
            except ValueError:
                logger.warn(f"Rate-limiting header values malformed (X-RateLimit-Reset-After: {params.response.headers['X-RateLimit-Reset-After']}; X-RateLimit-Limit: {params.response.headers['X-RateLimit-Limit']}; X-RateLimit-Remaining: {params.response.headers['X-RateLimit-Remaining']})")
            except KeyError:
                logger.warn("No rate-limiting headers received in response to DELETE")
            except ZeroDivisionError:
                logger.warn("Rate-limiting headers suggest that we cannot make any requests")

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user.name}#{self.user.discriminator} (ID: {self.user.id})")

        # Only start this loop once.
        if self.started:
            return

        self.started = True

        logger.info("Registering slash commands...")
        self.tree.add_command(AutodeleteCommands(self, self.config, name="autodelete"))
        await self.tree.sync()

        while True:
            logger.info("-- New scan --")
            try:
                await self.delete_old_messages()
            except Exception as e:
                logger.exception("Uncaught exception in main loop iteration; waiting until the next one", e)
            await asyncio.sleep(max(self.config.get_scan_interval(), 2) * 60)

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)

        if channel and self.config.is_channel_set(payload.channel_id):
            logger.info(f"Message deleted in #{channel.name} (ID: {payload.channel_id})")

    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)

        if channel and self.config.is_channel_set(payload.channel_id):
            logger.info(f"{len(payload.message_ids)} messages deleted in #{channel.name} (ID: {payload.channel_id})")

    async def get_channel_deletable_messages(self, channel, time_threshold: Optional[int], max_messages: Optional[int]) -> Sequence[discord.Message]:
        """Scans the given channel for messages that can be deleted given the current
           configuration and returns a sequence of those messages.

           In:
             channel: The channel instance to scan for deletable messages.
             time_threshold: The number of minutes of history before which messages
               are deletable, or None if this is not to be used as a criterion.
             max_messages: The maximum number of messages to leave in the channel,
               or None if this is not to be used as a criterion.
           Returns:
             A sequence of discord.Message objects that represent deletable
             messages."""
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

    async def delete_messages(self, messages: Sequence[discord.Message]) -> None:
        """Deletes the given messages from the channel that contains them using a
           single Bulk Delete Messages call if possible, falling back to single
           deletions if it fails.

           In:
             messages: A sequence of discord.Message objects representing the
               messages to be deleted. They must all belong to the same channel."""
        if len(messages) > 100:
            messages = list(messages)  # Only index on a proper list
            for i in range(0, len(messages), 100):
                await self.delete_messages(messages[i : i+100])
        elif len(messages):
            channel = messages[0].channel
            try:
                await asyncio.sleep(self.config.get_rate_limit())
                await channel.delete_messages(messages)
            except discord.NotFound as e:  # only if it resolves to a single message
                logger.info(f"Message ID {messages[0].id} in #{channel.name} (ID: {channel.id}) was deleted since scanning")
            except discord.ClientException as e:
                logger.exception(f"Failed to bulk delete {len(messages)} messages in #{channel.name} (ID: {channel.id}) due to the API considering the count to be too large; falling back to individual deletions", exc_info=e)
                for message in messages:
                    await self.delete_message(message)
            except discord.HTTPException as e:
                logger.info(f"Failed to bulk delete {len(messages)} messages in #{channel.name} (ID: {channel.id}); falling back to individual deletions", exc_info=e)
                for message in messages:
                    await self.delete_message(message)

    async def delete_message(self, message: discord.Message) -> None:
        """Deletes the given message from the channel that contains it.

           In:
             message: A discord.Message object representing the message to be
             deleted."""
        try:
            await asyncio.sleep(self.config.get_rate_limit())
            await message.delete()
        except discord.NotFound as e:
            logger.info(f"Message ID {message.id} in #{message.channel.name} (ID: {message.channel.id}) was deleted since scanning")
        except discord.HTTPException as e:
            logger.exception(f"Failed to delete message ID {message.id} in #{message.channel.name} (ID: {message.channel.id})", exc_info=e)

    async def delete_channel_deletable_messages(self, messages: Sequence[discord.Message]) -> None:
        """Deletes the given sequence of messages, which must all be part of the
           same channel, balancing using the fewest possible API calls with
           polluting the Audit Log as little as possible.

           In:
             messages: The list of messages to delete."""
        if len(messages) >= self.config.get_bulk_delete_min():
            # The Bulk Delete Messages API call only supports deleting messages
            # up to 14 days ago:
            # https://discord.com/developers/docs/resources/channel#bulk-delete-messages
            # (Why? https://github.com/discord/discord-api-docs/issues/208)
            time_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
            batch = []  # The batch of messages we are accumulating for Bulk Delete

            for message in messages:
                if message.created_at < time_cutoff:  # too old; delete single
                    await self.delete_message(message)
                else:  # add to the batch
                    batch.append(message)
                    if len(batch) == 100:
                        await self.delete_messages(batch)
                        batch = []

            if len(batch):
                await self.delete_messages(batch)
        else:
            for message in messages:
                await self.delete_message(message)

    async def delete_old_messages(self) -> None:
        """Deletes deletable messages from all configured channels."""
        self.config.set_rate_limit(0)

        to_delete: list[Tuple[discord.Channel, Sequence[discord.Message]]] = []

        # Copy the list from self.config so that we may delete from it with
        # clear_channel if a channel is no longer on the server.
        for channel_id in list(self.config.get_channels()):
            channel_config = self.config.get_channel_config(channel_id)
            time_threshold = channel_config.get("time_threshold", None)
            max_messages = channel_config.get("max_messages", None)
            try:
                channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            except discord.NotFound:
                channel = None
            if channel:
                try:
                    deletable_messages = await self.get_channel_deletable_messages(channel, time_threshold=time_threshold, max_messages=max_messages)
                    logger.info(f"#{channel.name} (ID: {channel_id}) has {len(deletable_messages)} messages to delete.")
                    to_delete.append((channel, deletable_messages))
                except Exception as e:
                    logger.exception(f"Failed to scan for messages to delete in #{channel.name} (ID: {channel_id})", exc_info=e)
            else:
                logger.error(f"Channel not found: {channel_id}; removing from auto-delete")
                self.config.clear_channel(channel_id)

        for channel, deletable_messages in to_delete:
            try:
                await self.delete_channel_deletable_messages(deletable_messages)
            except Exception as e:
                logger.exception(f"Failed to delete messages in #{channel.name} (ID: {channel.id})", exc_info=e)

if __name__ == '__main__':
    # Configure logging
    log_filename = "melodelete.log"
    log_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), log_filename)

    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(name)-15s %(levelname)-8s %(message)s',
                        handlers=[
                            logging.FileHandler(log_filepath),
                            logging.StreamHandler()
                        ])

    # Run the bot
    while True:
        try:
            Melodelete().run(log_handler=None)
        # Sometimes a WebSocketError is raised whenever a fragmented control
        # frame arrives, which may simply be a symptom of packet loss. This,
        # however, causes run() to return. We need to restart the bot.
        except aiohttp.http_websocket.WebSocketError as e:
            logger.exception("Transport error; reconnecting in 60 seconds", e)
            time.sleep(60)
        else:  # no WebSocketError has been raised; allow KeyboardInterrupt etc.
            break
