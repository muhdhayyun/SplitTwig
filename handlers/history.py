from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import delete_expense, ensure_member, get_currency, get_members, get_recent_expenses


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    expenses = get_recent_expenses(group_id)
    if not expenses:
        await update.message.reply_text("📋 No expenses recorded yet.")
        return

    members = {m["user_id"]: m for m in get_members(group_id)}
    currency = get_currency(group_id)

    lines = ["📋 *Recent Expenses*\n"]
    keyboard = []

    for exp in expenses:
        payer = members.get(exp["paid_by"])
        payer_name = payer["display_name"] if payer else f"User {exp['paid_by']}"
        date = datetime.fromisoformat(exp["created_at"]).strftime("%b %d")
        n = len(exp["split_ids"].split(","))

        lines.append(
            f"#{exp['id']} *{payer_name}* → {currency}{exp['amount']:.2f} _{exp['description']}_ · {date} ({n} people)"
        )
        keyboard.append([
            InlineKeyboardButton(
                f"🗑️ #{exp['id']} {exp['description']} ({currency}{exp['amount']:.2f})",
                callback_data=f"del:{exp['id']}",
            )
        ])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":")[1])
    keyboard = [[
        InlineKeyboardButton("✅ Delete", callback_data=f"delok:{expense_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data="delcancel"),
    ]]
    await query.edit_message_text(
        f"🗑️ Delete expense #{expense_id}? This cannot be undone.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":")[1])
    success = delete_expense(expense_id, query.from_user.id, update.effective_chat.id)

    if success:
        await query.edit_message_text(f"✅ Expense #{expense_id} deleted.")
    else:
        await query.edit_message_text("❌ Only the person who added this expense can delete it.")


async def delete_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Deletion cancelled.")
