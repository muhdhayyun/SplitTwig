from telegram import Update
from telegram.ext import ContextTypes

from db import ensure_member

HELP_TEXT = """💰 *SplitBot — Commands*

*Add an expense:*
/add — guided flow with buttons
/add 45 dinner — quick add (split everyone)

*View:*
/balance — who owes whom
/history — last 10 expenses
/members — group members list

*Settle up:*
Tap the 💸 *Settle* button on /balance
or: /paid @username 30

*Settings:*
/currency MYR — set group currency (USD, MYR, SGD…)

/help — show this message"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_member(
        update.effective_chat.id,
        user.id,
        user.username or "",
        user.full_name,
    )
    await update.message.reply_text(
        f"👋 Hey {user.first_name}, welcome to SplitBot!\n\n{HELP_TEXT}",
        parse_mode="Markdown",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
