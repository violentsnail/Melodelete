import json
import os
from datetime import datetime, timedelta, timezone
import logging

from typing import Any, Sequence, Mapping, Optional, Union

logger = logging.getLogger("melodelete.config")

def apply_defaults(config_dict: Mapping) -> Mapping:
    """Sets default values in the configuration dictionary if they are not set.

       In:
         config_dict: The configuration dictionary.
       Returns:
         config_dict."""
    if "bulk_delete_min" not in config_dict:
        config_dict["bulk_delete_min"] = 100
    if "scan_interval" not in config_dict:
        config_dict["scan_interval"] = 2
    if "channels" not in config_dict:
        config_dict["channels"] = []
    if "allowed_roles" not in config_dict:
        config_dict["allowed_roles"] = []
    return config_dict

def migrate_channel_settings(config_dict: Mapping) -> Mapping:
    """Rewrites the configuration dictionary to have a dictionary of channels,
       mapping channel IDs to their associated settings, rather than a list if
       it is one."""
    if "channels" in config_dict:
        channels_orig = config_dict["channels"]
        if is_mapping(config_dict["channels"]):
            # Make sure channel IDs are ints. JSON stores them as strings.
            # TODO: Remove this code for database config.
            channels_new = {int(k): v for k, v in channels_orig.items()}
        else:
            # Map each {id: int, others: their values} dict in the input list
            # to id: {others: their values} within the output dict.
            channels_new = {int(element["id"]): {k: v for k, v in element.items() if k != "id"} for element in channels_orig}
        config_dict["channels"] = channels_new
    return config_dict

def is_mapping(obj) -> bool:
    """Determines whether the given object is a mapping-like object."""
    # https://stackoverflow.com/a/21970190
    return hasattr(obj, 'keys') and hasattr(type(obj), '__getitem__')

class Config:
    def __init__(self) -> None:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        self.config_file = os.path.join(script_dir, "config.json")
        self.config = self.load_config()

    def load_config(self) -> Mapping:
        """Retrieves the configuration from file."""
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

        config = migrate_channel_settings(config)
        config = apply_defaults(config)
        return config

    def save_config(self) -> None:
        """Saves the configuration to file."""
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    def get_channels(self) -> Sequence[int]:
        """Retrieves the list of channels configured for autodelete on the
           server. See also: get_server_id()."""
        return self.config["channels"].keys()

    def get_channel_config(self, channel_id: int) -> Mapping[str, Any]:
        """Retrieves the autodelete configuration for a channel given its ID,
           or None if the channel is not configured for autodelete."""
        return self.config["channels"].get(channel_id)

    def is_channel_set(self, channel_id: int) -> bool:
        """Determines whether the given channel is configured for autodelete."""
        return channel_id in self.config["channels"]

    def get_token(self) -> str:
        """Retrieves the bot token from the configuration."""
        return self.config["token"]

    def get_server_id(self) -> int:
        """Retrieves the ID of the server on which autodelete will run."""
        return int(self.config["server_id"])

    def get_allowed_roles(self) -> Sequence[Union[int, str]]:
        """Retrieves the list of role names and IDs allowed to issue bot
           commands."""
        return self.config["allowed_roles"]

    def is_role_allowed(self, role: Union[int, str]) -> bool:
        """Determines whether a role ID or name is allowed to issue bot
           commands."""
        return role in self.get_allowed_roles()

    def add_allowed_role(self, role: Union[int, str]) -> None:
        """Adds a role ID or name to the list of roles allowed to issue bot
           commands."""
        if role not in self.get_allowed_roles():
            self.config["allowed_roles"].append(role)

            self.save_config()

    def clear_allowed_role(self, role: Union[int, str]) -> None:
        """Removes a role ID or name from the list of roles allowed to issue bot
           commands."""
        try:
            del self.config["allowed_roles"][self.config["allowed_roles"].index(role)]

            self.save_config()
        except ValueError:
            pass

    def set_channel(self, channel_id: int, time_threshold: Optional[int], max_messages: Optional[int]) -> None:
        """Sets the autodelete configuration for a channel to the given values.

           In:
             channel_id: The ID of the channel whose configuration is to be set.
             time_threshold: The number of minutes of messages to preserve in
               the given channel.
             max_messages: The number of recent messages to preserve in the
               given channel."""
        channel = self.get_channel_config(channel_id)
        if channel is None:
            channel = {}
            self.config["channels"][channel_id] = channel

        channel.pop("time_threshold", None)  # prepare for resetting
        channel.pop("max_messages", None)    # these two attributes
        if time_threshold is not None:
            channel["time_threshold"] = time_threshold
        if max_messages is not None:
            channel["max_messages"] = max_messages

        self.save_config()

    def clear_channel(self, channel_id: int) -> None:
        """Removes the autodelete configuration for a channel.

           In:
             channel_id: The ID of the channel whose configuration is to be
               removed."""
        try:
            del self.config["channels"][channel_id]
        except KeyError:
            pass
        else:
            self.save_config()

    def get_rate_limit(self) -> float:
        """Retrieves the current rate limit in seconds."""
        return self.rate_limit

    def set_rate_limit(self, rate_limit: Union[int, float]) -> None:
        """Sets the current rate limit in seconds."""
        self.rate_limit = float(rate_limit)

    def get_bulk_delete_min(self) -> int:
        """Retrieves the minimum number of deletable messages in a single
           channel for the bot to use Bulk Delete Messages to delete them
           all."""
        return self.config["bulk_delete_min"]

    def set_bulk_delete_min(self, bulk_delete_min: int) -> None:
        """Sets the minimum number of deletable messages in a single channel
           for the bot to use Bulk Delete Messages to delete them all."""
        self.config["bulk_delete_min"] = bulk_delete_min

        self.save_config()

    def get_scan_interval(self) -> int:
        """Retrieves the delay between scans for deletable messages, in minutes."""
        return self.config["scan_interval"]

    def set_scan_interval(self, scan_interval: int) -> None:
        """Sets the delay between scans for deletable messages, in minutes."""
        self.config["scan_interval"] = scan_interval

        self.save_config()
