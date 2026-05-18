from telegram import Update
from telegram.ext import ContextTypes

from db import ensure_member, get_currency, get_members, set_currency


async def members_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    members = get_members(group_id)
    currency = get_currency(group_id)

    lines = [f"👥 *Group Members* ({len(members)})  |  Currency: {currency}\n"]
    for m in members:
        name = m["display_name"] or m["username"] or f"User {m['user_id']}"
        handle = f" (@{m['username']})" if m["username"] else ""
        lines.append(f"• {name}{handle}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def currency_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id

    if not context.args:
        current = get_currency(group_id)
        await update.message.reply_text(
            f"Current currency: *{current}*\nUsage: `/currency MYR`\nExamples: USD, MYR, SGD, EUR, GBP",
            parse_mode="Markdown",
        )
        return

    code = context.args[0].upper().strip()
    if len(code) != 3 or not code.isalpha():
        await update.message.reply_text("❌ Currency must be a 3-letter code (e.g. USD, MYR, SGD)")
        return

    set_currency(group_id, code)
    await update.message.reply_text(f"✅ Currency set to *{code}*", parse_mode="Markdown")
