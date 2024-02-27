import discord
import json
import asyncio
import aiohttp
import os
from datetime import datetime, timedelta, timezone
import logging

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

# Function to load channels from the config.json file
def load_channels():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_file = os.path.join(script_dir, "config.json")
    with open(config_file) as f:
        config = json.load(f)
    return config["channels"]

# Check if the config.json file exists, otherwise create it with default values
script_dir = os.path.dirname(os.path.realpath(__file__))
config_file = os.path.join(script_dir, "config.json")

if not os.path.exists(config_file):
    default_config = {
        "token": "YOUR_DISCORD_BOT_TOKEN",
        "server_id": "YOUR_SERVER_ID",
        "channels": [],
        "allowed_roles": []
    }

    with open(config_file, "w") as f:
        json.dump(default_config, f, indent=4)
        logger.critical("config.json created. Please update the token, server ID, and other settings before running the bot.")
        exit()

# Discord bot token, server ID, and allowed roles from the config
with open(config_file) as f:
    config = json.load(f)
TOKEN = config["token"]
SERVER_ID = config["server_id"]
ALLOWED_ROLES = config["allowed_roles"]

# Create a Discord client
intents = discord.Intents.default()
intents.messages = True
intents.reactions = False
intents.typing = False

# Set up an HTTP request tracer that will let us know what the current rate
# limit is for deletions.

rate_limit = 0

async def on_request_end(session, trace_config_ctx, params):
    if params.method == "DELETE":  # Message deletions use the DELETE HTTP method
        global rate_limit
        try:
            if int(params.response.headers["X-RateLimit-Remaining"]) == 0:
                # We have hit the limit and can therefore define it.
                # The time to reset is assumed to apply equally to every
                # request before this one.
                rate_limit = float(params.response.headers["X-RateLimit-Reset-After"]) / int(params.response.headers["X-RateLimit-Limit"])
                logger.info(f"Rate limit is now {rate_limit} seconds")
        except ValueError:
            logger.warn(f"Rate-limiting header values malformed (X-RateLimit-Reset-After: {params.response.headers['X-RateLimit-Reset-After']}; X-RateLimit-Limit: {params.response.headers['X-RateLimit-Limit']}; X-RateLimit-Remaining: {params.response.headers['X-RateLimit-Remaining']})")
        except KeyError:
            logger.warn("No rate-limiting headers received in response to DELETE")
        except ZeroDivisionError:
            logger.warn("Rate-limiting headers suggest that we cannot make any requests")

trace_config = aiohttp.TraceConfig()
trace_config.on_request_end.append(on_request_end)

client = discord.Client(intents=intents, http_trace=trace_config)

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

"""Deletes the given sequence of messages, which must all be part of the same
   channel.

   In:
     messages: The list of messages to delete."""
async def delete_channel_deletable_messages(messages):
    global rate_limit

    for message in messages:
        await asyncio.sleep(rate_limit)
        await message.delete()

"""Deletes deletable messages from all configured channels."""
async def delete_old_messages():
    CHANNELS = load_channels()

    global rate_limit
    rate_limit = 0

    to_delete = []  # List of tuples of (Channel, List[Message])

    for channel_config in CHANNELS:
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

@client.event
async def on_message(message):
    # Load the updated channel list from the config.json file
    CHANNELS = load_channels()

    if message.author == client.user:
        return

    # If the message starts with a mention of this bot
    if message.content.startswith(f"<@{client.user.id}>"):
        # Check if the user has an allowed role
        user_roles = [role.name for role in message.author.roles]
        if not any(role in user_roles for role in ALLOWED_ROLES):
            await message.channel.send("You don't have permission to use this command.")
            return

        # Then parse out the command after the mention
        command = message.content[len(f"<@{client.user.id}>"):].strip()
        if command == "ping":
            await message.channel.send("Hi there! You have permission to use commands.")
        elif command == "clear":
            # Remove channel entry from CHANNELS and config.json
            CHANNELS = [channel for channel in CHANNELS if channel["id"] != message.channel.id]
            config["channels"] = CHANNELS
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
            await message.channel.send("This channel has been removed from auto-delete.")
        elif command == "refresh":
            await message.channel.send("Refreshing message deletion...")
            await delete_old_messages()  # Call the delete_old_messages function on refresh command
        elif command == "config":
            for channel_config in CHANNELS:
                if message.channel.id == channel_config["id"]:
                    time_threshold_hours = channel_config["time_threshold"] // 60 if "time_threshold" in channel_config else "Not set"
                    max_messages = channel_config["max_messages"] if "max_messages" in channel_config else "Not set"
                    await message.channel.send(f"Current settings for this channel:\n- Time threshold: {time_threshold_hours} hours\n- Max messages: {max_messages}")
                    return
            await message.channel.send("This channel is not configured for auto-delete.")
        else:
            command_parts = command.split()
            if len(command_parts) >= 2:
                time_str = None
                max_messages_str = None

                for part in command_parts[1:]:
                    if part.startswith("-h"):
                        time_str = part[2:]
                    elif part.startswith("-max"):
                        max_messages_str = part[4:]

                time_threshold = None
                max_messages = None

                if time_str:
                    try:
                        hours = int(time_str)
                        time_threshold = hours * 60  # Convert hours to minutes
                    except ValueError:
                        await message.channel.send("Invalid time format. Please use a whole number for the hours.")
                        return

                if max_messages_str:
                    try:
                        max_messages = int(max_messages_str)
                    except ValueError:
                        await message.channel.send("Invalid max messages format. Please use a whole number for the max messages.")
                        return

                if time_threshold is None and max_messages is None:
                    await message.channel.send("Please specify either -h or -max.")
                    return

                # Update the settings for the channel or create a new entry
                found_channel = False
                for channel_config in CHANNELS:
                    if message.channel.id == channel_config["id"]:
                        if time_threshold is not None:
                            channel_config["time_threshold"] = time_threshold
                        if max_messages is not None:
                            channel_config["max_messages"] = max_messages
                        found_channel = True
                        break

                if not found_channel:
                    new_channel = {
                        "id": message.channel.id,
                        "time_threshold": time_threshold,
                        "max_messages": max_messages
                    }
                    CHANNELS.append(new_channel)

                # Save the updated configuration to the file
                config["channels"] = CHANNELS
                with open("config.json", "w") as f:
                    json.dump(config, f, indent=4)

                if time_threshold is not None and max_messages is not None:
                    await message.channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted, and there will be a maximum of {max_messages} messages.")
                elif time_threshold is not None:
                    await message.channel.send(f"Auto-delete settings for this channel have been updated: messages older than {hours} hours will be deleted.")
                elif max_messages is not None:
                    await message.channel.send(f"Auto-delete settings for this channel have been updated: there will be a maximum of {max_messages} messages.")

@client.event
async def on_raw_message_delete(payload):
    CHANNELS = load_channels()
    channel = client.get_channel(payload.channel_id)

    if channel and payload.channel_id in [channel["id"] for channel in CHANNELS]:
        logger.info(f"Message deleted in #{channel.name} (ID: {payload.channel_id})")

# Run the bot
client.run(TOKEN, log_handler=None)