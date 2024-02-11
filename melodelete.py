import discord
import json
import asyncio
import os
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
log_filename = "melodelete.log"
log_filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)), log_filename)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s',
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
        print("config.json created. Please update the token, server ID, and other settings before running the bot.")
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
client = discord.Client(intents=intents)

# Counts the total number of messages that need to be deleted for performance purposes.
async def count_messages_to_delete():
    CHANNELS = load_channels()
    for channel_config in CHANNELS:
        channel_id = channel_config["id"]
        time_threshold = channel_config.get("time_threshold", None)
        max_messages = channel_config.get("max_messages", None)

        channel = client.get_channel(channel_id)
        if channel:
            try:
                messages_to_delete = 0
                all_messages = [message async for message in channel.history(limit=None)]

                if time_threshold:
                    threshold_time = datetime.now(timezone.utc) - timedelta(minutes=time_threshold)
                    messages_to_delete += len([message for message in all_messages if message.created_at < threshold_time and not message.pinned])

                if max_messages and len(all_messages) > max_messages:
                    messages_to_delete += len(all_messages) - max_messages

                print(f"Channel {channel.name} (ID: {channel_id}) has {messages_to_delete} messages to delete.")
                #logging.info(f"Channel {channel.name} (ID: {channel_id}) has {messages_to_delete} messages to delete.")
            except Exception as e:
                print(f"Error in count_messages_to_delete for channel {channel.name} (ID: {channel_id}): {e}")
                #logging.info(f"Error in count_messages_to_delete for channel {channel.name} (ID: {channel_id}): {e}")
        else:
            print(f"Channel not found: {channel_id}")


# Function to delete old messages from the watched channels
async def delete_old_messages():
    CHANNELS = load_channels()

    for channel_config in CHANNELS:
        channel_id = channel_config["id"]
        time_threshold = channel_config.get("time_threshold", None)
        max_messages = channel_config.get("max_messages", None)

        channel = client.get_channel(channel_id)
        if channel:
            try:
                if time_threshold:
                    threshold_time = datetime.now(timezone.utc) - timedelta(minutes=time_threshold)
                    async for message in channel.history(limit=None):
                        if message.created_at < threshold_time and not message.pinned:
                            await message.delete()
                            await asyncio.sleep(30)  # Delay to avoid rate limiting
                    # Additional sleep to ensure completion of time_threshold deletions
                    await asyncio.sleep(5)

                if max_messages:
                    messages = [message async for message in channel.history(limit=max_messages + 1)]
                    if len(messages) > max_messages:
                        for message in messages[max_messages:]:
                            await message.delete()
                            await asyncio.sleep(30  )  # Delay to avoid rate limiting
            except Exception as e:
                print(f"Error in delete_old_messages for channel {channel.name} (ID: {channel_id}): {e}")
        else:
            print(f"Channel not found: {channel_id}")

@client.event
async def on_ready():
    print(f"Logged in as {client.user.name}")
    #logging.info(f"Logged in as {client.user.name}")
    
    await count_messages_to_delete()
    print("------")
    #logging.info("------")

    # Call the delete_old_messages function on startup
    await delete_old_messages()

@client.event
async def on_message(message):
    # Load the updated channel list from the config.json file
    CHANNELS = load_channels()

    if message.author == client.user:
        return

    if message.content.startswith(".autoping"):
        # Check if the user has an allowed role
        user_roles = [role.name for role in message.author.roles]
        if any(role in user_roles for role in ALLOWED_ROLES):
            await message.channel.send("Permissions Check: Valid")
        else:
            await message.channel.send("ACCESS DENIED, invalid perms")
        return

    if message.content.startswith(".autodelete"):
        # Check if the user has an allowed role
        user_roles = [role.name for role in message.author.roles]
        if not any(role in user_roles for role in ALLOWED_ROLES):
            await message.channel.send("You don't have permission to use this command.")
            return

        # Check if the command is '.autodelete clear'
        if message.content.strip() == ".autodelete clear":
            # Remove channel entry from CHANNELS and config.json
            CHANNELS = [channel for channel in CHANNELS if channel["id"] != message.channel.id]
            config["channels"] = CHANNELS
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
            await message.channel.send("This channel has been removed from auto-delete.")
            return

        # Check if the command is '.autodelete refresh'
        if message.content.strip() == ".autodelete refresh":
            await message.channel.send("Refreshing message deletion...")
            await delete_old_messages()  # Call the delete_old_messages function on refresh command
            return

        # Check if the command is '.autodelete config'
        if message.content.strip() == ".autodelete config":
            for channel_config in CHANNELS:
                if message.channel.id == channel_config["id"]:
                    time_threshold_hours = channel_config["time_threshold"] // 60 if "time_threshold" in channel_config else "Not set"
                    max_messages = channel_config["max_messages"] if "max_messages" in channel_config else "Not set"
                    await message.channel.send(f"Current settings for this channel:\n- Time threshold: {time_threshold_hours} hours\n- Max messages: {max_messages}")
                    return
            await message.channel.send("This channel is not configured for auto-delete.")
            return

        # Handle the rest of the command...
        command_parts = message.content.split()
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
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{current_time}] Message deleted in {channel.name} (ID: {payload.channel_id})")
        #logging.info(f"Message deleted in {channel.name} (ID: {payload.channel_id})")

# Run the bot
client.run(TOKEN)