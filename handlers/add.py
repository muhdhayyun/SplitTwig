import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from db import add_expense, ensure_member, get_currency, get_members

logger = logging.getLogger(__name__)


def esc(text: str) -> str:
    """Escape Markdown special characters in user-provided strings."""
    for ch in ("_", "*", "[", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text
AMOUNT, DESCRIPTION, MEMBERS = range(3)


def _find_member_by_mention(members: list, mention: str):
    target = mention.lstrip("@").lower()
    for m in members:
        uname = (m["username"] or "").lower()
        dname = (m["display_name"] or "").lower().lstrip("@")
        if uname == target or dname == target:
            return m
    return None


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)
    logger.info("add_start: user=%s (%s) group=%s args=%s", user.id, user.username, group_id, context.args)

    args = context.args

    # /add @user 45 dinner — log a payment on behalf of another user
    if args and args[0].startswith("@"):
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: `/add @user 45 dinner`", parse_mode="Markdown"
            )
            return ConversationHandler.END
        members = get_members(group_id)
        target = _find_member_by_mention(members, args[0])
        if not target:
            await update.message.reply_text(f"❌ {args[0]} not found in this group.")
            return ConversationHandler.END
        try:
            amount = float(args[1].replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text(f"❌ Invalid amount: `{args[1]}`", parse_mode="Markdown")
            return ConversationHandler.END
        description = " ".join(args[2:])
        context.user_data["add"] = {
            "amount": amount,
            "description": description,
            "paid_by": target["user_id"],
        }
        return await _show_members(update, context)

    # Quick-add: /add 45 dinner
    if args and len(args) >= 2:
        try:
            amount = float(args[0].replace(",", "."))
            if amount <= 0:
                raise ValueError
            description = " ".join(args[1:])
            context.user_data["add"] = {"amount": amount, "description": description}
            return await _show_members(update, context)
        except ValueError:
            logger.warning("add_start: invalid quick-add args %s", args)
            pass

    await update.message.reply_text("💰 How much did you pay?\n_(e.g. `45` or `12.50`)_", parse_mode="Markdown")
    context.user_data["add"] = {}
    return AMOUNT


async def got_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.strip().replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number (e.g. `45` or `12.50`)", parse_mode="Markdown")
        return AMOUNT

    context.user_data["add"]["amount"] = amount
    await update.message.reply_text("📝 What was it for?")
    return DESCRIPTION


async def got_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["add"]["description"] = update.message.text.strip()
    return await _show_members(update, context)


async def _show_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    members = get_members(group_id)
    data = context.user_data["add"]
    amount = data["amount"]
    currency = get_currency(group_id)

    # First time showing: pre-select everyone
    if "selected" not in data:
        data["selected"] = {m["user_id"] for m in members}

    selected = data["selected"]
    n = len(selected)
    share = round(amount / n, 2) if n > 0 else 0.0

    keyboard = []
    for m in members:
        tick = "✅" if m["user_id"] in selected else "⬜"
        name = m["display_name"] or m["username"] or f"User {m['user_id']}"
        keyboard.append([InlineKeyboardButton(f"{tick} {name}", callback_data=f"addtog:{m['user_id']}")])

    keyboard.append([
        InlineKeyboardButton(
            f"✓ Confirm — {currency}{share:.2f} each ({n} people)",
            callback_data="addok",
        )
    ])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="addcancel")])

    text = f"👥 *Split among who?*\n💰 Total: {currency}{amount:.2f}"
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

    return MEMBERS


async def toggle_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = int(query.data.split(":")[1])
    selected: set = context.user_data["add"]["selected"]

    if uid in selected:
        if len(selected) > 1:
            selected.discard(uid)
        else:
            await query.answer("At least one person must be selected!", show_alert=True)
            return MEMBERS
    else:
        selected.add(uid)

    return await _show_members(update, context)


async def confirm_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("add")
    if not data:
        logger.warning("confirm_add: no session data for user=%s", update.effective_user.id)
        await query.edit_message_text("❌ Session expired — please start over with /add")
        return ConversationHandler.END

    selected = list(data["selected"])
    user = update.effective_user
    group_id = update.effective_chat.id
    paid_by = data.get("paid_by", user.id)
    logger.info("confirm_add: user=%s paid_by=%s group=%s amount=%s desc=%s selected=%s",
                user.id, paid_by, group_id, data.get("amount"), data.get("description"), selected)

    # Require at least one person other than the payer
    others = [uid for uid in selected if uid != paid_by]
    if not others:
        await query.answer("Select at least one other person to split with!", show_alert=True)
        return MEMBERS

    try:
        expense_id = add_expense(group_id, paid_by, data["amount"], data["description"], selected)
    except Exception:
        logger.exception("confirm_add: failed to save expense")
        await query.edit_message_text("❌ Failed to save expense — check the bot logs.")
        return ConversationHandler.END

    currency = get_currency(group_id)
    n = len(selected)
    share = round(data["amount"] / n, 2)

    members = {m["user_id"]: m for m in get_members(group_id)}
    payer = members.get(paid_by)
    payer_name = (payer["display_name"] or payer["username"] or f"User {paid_by}") if payer else user.full_name
    payer_name = payer_name.lstrip("@")

    other_names = ", ".join(
        esc((members[uid]["display_name"] or members[uid]["username"] or f"User {uid}").lstrip("@"))
        for uid in others
        if uid in members
    )

    text = (
        f"✅ *{esc(payer_name)}* paid *{currency}{data['amount']:.2f}* for _{esc(data['description'])}_\n"
        f"Split {n} ways ({currency}{share:.2f} each)"
    )
    if other_names:
        text += f"\n→ owes *{esc(payer_name)}*: {other_names}"

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Delete", callback_data=f"del:{expense_id}")]])
    await query.edit_message_text(text, reply_markup=markup, parse_mode="Markdown")

    context.user_data.pop("add", None)
    return ConversationHandler.END


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("add", None)
    await query.edit_message_text("❌ Cancelled.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("add", None)
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


add_handler = ConversationHandler(
    entry_points=[CommandHandler("add", add_start)],
    states={
        AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_amount)],
        DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_description)],
        MEMBERS: [
            CallbackQueryHandler(toggle_member, pattern=r"^addtog:"),
            CallbackQueryHandler(confirm_add,   pattern=r"^addok$"),
            CallbackQueryHandler(cancel_add,    pattern=r"^addcancel$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_command)],
    allow_reentry=True,
    per_chat=True,
    per_user=True,
)
