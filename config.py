import json
import os
from datetime import datetime, timedelta, timezone
import logging

from typing import Sequence, Mapping, Optional, Union

logger = logging.getLogger("melodelete.config")

"""Sets default values in the configuration dictionary if they are not set.

   In:
     config_dict: The configuration dictionary.
   Returns:
     config_dict."""
def apply_defaults(config_dict: Mapping) -> Mapping:
    if "bulk_delete_min" not in config_dict:
        config_dict["bulk_delete_min"] = 100
    if "channels" not in config_dict:
        config_dict["channels"] = []
    if "allowed_roles" not in config_dict:
        config_dict["allowed_roles"] = []
    return config_dict

class Config:
    def __init__(self) -> None:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        self.config_file = os.path.join(script_dir, "config.json")
        self.config = self.load_config()

    """Retrieves the configuration from file."""
    def load_config(self):
        # Check if the config.json file exists, otherwise create it with default values
        if not os.path.exists(self.config_file):
            default_config = apply_defaults({
                "token": "YOUR_DISCORD_BOT_TOKEN",
                "server_id": "YOUR_SERVER_ID",
            })
            with open(self.config_file, "w") as f:
                json.dump(default_config, f, indent=4)
                logger.critical("config.json created. Please update the token, server ID, and other settings before running the bot.")
                exit()

        with open(self.config_file) as f:
            config = json.load(f)

        if config["token"] == "YOUR_DISCORD_BOT_TOKEN" or config["server_id"] == "YOUR_SERVER_ID":
            logger.critical("Please update the token, server ID, and other settings in config.json before running the bot.")
            exit()

        return apply_defaults(config)

    """Saves the configuration to file."""
    def save_config(self) -> None:
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    """Retrieves the list of channels configured for autodelete on the server.
       See also: get_server_id()."""
    def get_channels(self) -> Sequence[Mapping[str, Optional[Union[str, int]]]]:
        return self.config["channels"]

    """Retrieves the bot token from the configuration."""
    def get_token(self) -> str:
        return self.config["token"]

    """Retrieves the ID of the server on which autodelete will run."""
    def get_server_id(self) -> int:
        return int(self.config["server_id"])

    """Retrieves the list of names of roles allowed to issue bot commands."""
    def get_allowed_role_names(self) -> Sequence[str]:
        return self.config["allowed_roles"]

    """Sets the autodelete configuration for a channel to the given values.
    
       In:
         channel_id: The ID of the channel whose configuration is to be set.
         time_threshold: The number of minutes of messages to preserve in the
           given channel.
         max_messages: The number of recent messages to preserve in the given
           channel."""
    def set_channel(self, channel_id: int, time_threshold: Optional[int], max_messages: Optional[int]):
        channels = self.get_channels()

        for channel_config in channels:
            if channel_id == channel_config["id"]:
                channel = channel_config
                break
        else:  # no channel was found
            channel = {
                "id": message.channel.id
            }
            channels.append(channel)

        channel.pop("time_threshold", None)  # prepare for resetting
        channel.pop("max_messages", None)    # these two attributes
        if time_threshold is not None:
            channel["time_threshold"] = time_threshold
        if max_messages is not None:
            channel["max_messages"] = max_messages

        self.save_config()

    """Removes the autodelete configuration for a channel.

       In:
         channel_id: The ID of the channel whose configuration is to be removed."""
    def clear_channel(self, channel_id: int) -> None:
        channels = self.get_channels()

        channels = [channel for channel in channels if channel["id"] != channel_id]

        self.save_config()

    """Retrieves the current rate limit in seconds."""
    def get_rate_limit(self) -> float:
        return self.rate_limit

    """Sets the current rate limit in seconds."""
    def set_rate_limit(self, rate_limit: Union[int, float]):
        self.rate_limit = float(rate_limit)

    """Retrieves the minimum number of deletable messages in a single channel
       for the bot to use Bulk Delete Messages to delete them all."""
    def get_bulk_delete_min(self) -> int:
        return self.config["bulk_delete_min"]

    """Sets the minimum number of deletable messages in a single channel for
       the bot to use Bulk Delete Messages to delete them all."""
    def set_bulk_delete_min(self, bulk_delete_min: int) -> None:
        self.config["bulk_delete_min"] = bulk_delete_min
