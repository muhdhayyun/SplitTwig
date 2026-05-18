# SplitBot — Telegram Expense Splitter

A personal Splitwise-style Telegram bot. Track shared expenses, split bills, and settle up — all inside Telegram.

## Setup

### 1. Get a Bot Token
1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts, copy the token

### 2. Disable Privacy Mode (required for group chats)
In BotFather: `/setprivacy` → select your bot → **Disable**
This lets the bot read messages needed for the multi-step `/add` flow.

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

1. Add the bot to your Telegram group
2. **Everyone** sends `/start` once — this registers them so they appear in expense splits

## Commands

| Command | Description |
|---|---|
| `/add` | Guided expense flow with buttons |
| `/add 45 dinner` | Quick add — skips to member selection |
| `/balance` | Show who owes whom with Settle buttons |
| `/history` | Last 10 expenses with Delete buttons |
| `/members` | List registered members |
| `/paid @username 30` | Record a manual payment |
| `/currency MYR` | Set group currency (default: USD) |
| `/help` | Show all commands |

## Moving to Another Laptop

The database is `data.db` — it's tracked by git intentionally.

**Before switching machines:**
```
git add data.db
git commit -m "sync db"
git push
```

**On the other laptop:**
```
git pull
python bot.py
```

> Only run one instance at a time. Telegram rejects duplicate token connections.

## Notes

- `.env` is gitignored — your bot token is never committed
- Each Telegram group has its own isolated expense pool
- The bot works in private chats (1-on-1) and group chats
