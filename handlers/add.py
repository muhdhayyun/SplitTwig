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

AMOUNT, DESCRIPTION, MEMBERS = range(3)


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    # Quick-add: /add 45 dinner
    args = context.args
    if args and len(args) >= 2:
        try:
            amount = float(args[0].replace(",", "."))
            if amount <= 0:
                raise ValueError
            description = " ".join(args[1:])
            context.user_data["add"] = {"amount": amount, "description": description}
            return await _show_members(update, context)
        except ValueError:
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
        await query.edit_message_text("❌ Session expired — please start over with /add")
        return ConversationHandler.END

    selected = list(data["selected"])
    user = update.effective_user
    group_id = update.effective_chat.id

    # Require at least one OTHER person
    others = [uid for uid in selected if uid != user.id]
    if not others:
        await query.answer("Select at least one other person to split with!", show_alert=True)
        return MEMBERS

    expense_id = add_expense(group_id, user.id, data["amount"], data["description"], selected)

    currency = get_currency(group_id)
    n = len(selected)
    share = round(data["amount"] / n, 2)

    members = {m["user_id"]: m for m in get_members(group_id)}
    other_names = ", ".join(
        (members[uid]["display_name"] or members[uid]["username"] or f"User {uid}")
        for uid in others
        if uid in members
    )

    text = (
        f"✅ *{user.full_name}* paid *{currency}{data['amount']:.2f}* for _{data['description']}_\n"
        f"Split {n} ways ({currency}{share:.2f} each)"
    )
    if other_names:
        text += f"\n→ owes you: {other_names}"

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
    per_chat=True,
    per_user=True,
)
