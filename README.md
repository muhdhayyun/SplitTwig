# SplitTwig — Telegram Expense Splitter

Telegram bot for splitting expenses in group chats — track who paid, who owes, and settle up easily.

## Setup

### 1. Get a Bot Token
1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts, copy the token

### 2. Disable Privacy Mode (required for group chats)
In BotFather: `/mybots` → select your bot → **Bot Settings → Group Privacy → Turn off**

This lets the bot read plain text messages needed for the multi-step `/add` flow.

### 3. Install & Configure
```
setup.bat
```
Then open `.env` and paste your token:
```
BOT_TOKEN=123456789:ABCdef...
```

### 4. Run
```
run.bat
```
or
```
python bot.py
```

## First Use in a Group

1. Add **SplitTwig** to your Telegram group and make it an admin
2. **Everyone** sends `/start` once — this registers them so they appear in expense splits
3. You can also add someone manually with `/addmember Name` if they haven't messaged the bot yet

## Commands

| Command | Description |
|---|---|
| `/add` | Guided expense flow with buttons |
| `/add 45 dinner` | Quick add — skips to member selection |
| `/balance` | Show who owes whom with itemised breakdown |
| `/history` | Recent expenses and payments |
| `/members` | List registered members |
| `/addmember Name` | Manually add a member by name |
| `/paid @username 30` | Record a manual payment |
| `/currency SGD` | Set group currency (default: SGD) |
| `/cancel` | Cancel the current action |
| `/help` | Show all commands |

## Moving to Another Machine

The database is `data.db` — copy or sync it to carry your expense history across machines.

> Only run one instance at a time. Telegram rejects duplicate token connections.

## Notes

- `.env` is gitignored — your bot token is never committed
- Each Telegram group has its own isolated expense pool
- When a manually added member later joins and types `/start`, their placeholder is automatically merged with their real Telegram account
