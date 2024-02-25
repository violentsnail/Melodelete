# Melodelete

Melodelete is a Discord bot that can be configured to run through messages on certain channels of a server and delete messages older than a certain age in hours or above a certain number of recent messages or both, preserving pinned messages.

## Setting up

To run Melodelete, you will need a computer with [Python 3](https://www.python.org/download/releases/3.0/) installed, as well as the `discord.py` package, which you can install with the following command:
```
pip3 install discord
```

You will then need an application ID and bot token, which you can obtain on the [Discord Developer Portal](https://discord.com/developers/applications) after creating an application and generating a bot token. Make sure to copy the bot token somewhere, as it is only ever displayed once, and you must reset the token, triggering two-factor authentication, to get another.

In the settings for your new application, go into Settings/Bot, and under Privileged Gateway Intents, enable:

> Message Content Intent
> Required for your bot to receive message content in most messages.

before saving the settings.

You may then add the bot to the server you wish to use it on by visiting a URL like this in a browser:
`https://discord.com/api/oauth2/authorize?client_id=APPLICATION_ID_GOES_HERE&permissions=76800&scope=bot`
where `APPLICATION_ID_GOES_HERE` is the application ID shown for the bot under Settings/General Information.

This gives the bot the following permissions on the server you select in the browser: Read Messages/View Channels, Read Message History, Send Messages, Manage Messages.

## Initial run and configuration

In the correct directory, run Melodelete on the command line:
```
python3 melodelete.py
```

It will create a skeleton `config.json` file for you to fill with your bot token and the ID of the server you want to automatically delete older messages on.

* The bot token is obtained during the process to create the Discord application. It is only displayed once after it is generated.
* To get the ID of a server, go into your Discord User Settings, then, under App Settings/Advanced, enable Developer Mode. Exit User Settings, then, on the server in question, right-click (Desktop or Web) or tap (Mobile) the server's header, then select Copy Server ID.

## Running

In the correct directory, run Melodelete on the command line:
```
python3 melodelete.py
```
