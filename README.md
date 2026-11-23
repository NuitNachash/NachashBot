# NachashBot

A multi-channel Twitch chat bot written in Python, built on the Twitch Helix API and EventSub WebSocket.

> **Reference only.** This repository is published to show how the bot is built. It is not a supported or turnkey project: the database schema and configuration are intentionally not included, and it is not intended to be cloned and run as-is.

## Features

- Real-time chat and stream events via EventSub WebSocket (`channel.chat.message`, `stream.online`, `stream.offline`)
- Multi-channel support, with each channel connecting through its own EventSub session
- Database-driven commands with per-channel overrides, aliases, and permission levels (everyone, VIP, moderator, broadcaster, trusted)
- Configurable command prefix per channel
- Chat message logging, watch-time tracking (live vs. offline), and stream session tracking
- Automatic OAuth token refresh for app, bot, and broadcaster tokens
- Flask-based OAuth flow for adding the bot to a channel
- Disk space monitoring with push notifications via ntfy

## Stack

- Python 3, `asyncio`, `aiohttp`
- PostgreSQL via `asyncpg` (plus `psycopg2` for a secondary VOD database)
- Flask (OAuth callback server)
- Twitch Helix API and EventSub

## Layout

| File | Purpose |
|------|---------|
| `main.py` / `bot.py` | Entry point, startup, and background tasks |
| `eventsub.py` | WebSocket connection, subscriptions, and event handling |
| `commands.py` | Command routing and handlers |
| `database_manager.py` | PostgreSQL access layer |
| `token_manager.py` | App, bot, and user token handling |
| `twitch_api.py` | Helix API helpers |
| `chat.py` | Sending chat messages |
| `logger.py` | Logging setup |


## Current Supported Commands

Commands use the channel's configured prefix. Custom commands added with `addcom` also work.

| Command | Usage | Description | Access |
|---------|-------|-------------|--------|
| `uptime` | `uptime` | Shows how long the stream has been live | Per-command permission |
| `followage` | `followage [user]` | Shows when a user followed the channel | Per-command permission |
| `firstmessage` | `firstmessage` | Shows your first logged message in the channel | Per-command permission |
| `randomquote` (alias `rq`) | `randomquote [user]` | Random logged message from a user | Per-command permission |
| `randomline` | `randomline` | Random logged message from anyone in the channel | Per-command permission |
| `optout` | `optout <command>` | Opt out of a command that uses your messages | Per-command permission |
| `timeout` | `timeout <user> [seconds]` | Times out a user (1 to 1,209,600 seconds) | Moderator |
| `ban` | `ban <user> [reason]` | Bans a user | Moderator |
| `createpoll` | `createpoll <duration> <title> \| <choice1> \| <choice2>` | Creates a poll | Moderator |
| `setprefix` | `setprefix <char>` | Changes the channel's command prefix | Moderator |
| `addcom` | `addcom <command> <permission> <response>` | Adds a custom command | Per-command permission |
| `editcom` | `editcom <command> <new response>` | Edits a custom command | Per-command permission |
| `delcom` | `delcom <command>` | Deletes a custom command | Per-command permission |
| `editperm` | `editperm <command> <permission>` | Changes a command's permission level | Per-command permission |

Permission levels: `everyone`, `vip`, `moderator`, `broadcaster`, `trusted`.

## Configuration

Credentials live in an untracked `config.py`; supply your own. Secrets should be supplied through environment variables or a local, untracked config file.

## License

Source-available under PolyForm Strict 1.0.0, provided for reference only.