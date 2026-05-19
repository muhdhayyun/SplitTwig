from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import delete_expense, ensure_member, get_balances, get_currency, get_members, get_recent_expenses, get_recent_settlements, simplify_debts


def esc(text: str) -> str:
    for ch in ("_", "*", "[", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    expenses = get_recent_expenses(group_id)
    settlements = get_recent_settlements(group_id)

    if not expenses and not settlements:
        await update.message.reply_text("📋 No expenses recorded yet.")
        return

    members = {m["user_id"]: m for m in get_members(group_id)}
    currency = get_currency(group_id)

    balances, _ = get_balances(group_id)
    outstanding = {(d, c) for d, c, _ in simplify_debts(balances)}

    def name(uid):
        m = members.get(uid)
        return m["display_name"] if m else f"User {uid}"

    # Merge expenses and settlements into one chronological list (newest first)
    events = []
    for exp in expenses:
        events.append(("expense", datetime.fromisoformat(exp["created_at"]), exp))
    for s in settlements:
        events.append(("settlement", datetime.fromisoformat(s["created_at"]), s))
    events.sort(key=lambda x: x[1], reverse=True)

    lines = ["📋 *Recent Activity*\n"]
    keyboard = []

    for kind, dt, row in events:
        date = dt.strftime("%b %d")
        if kind == "expense":
            payer_name = esc(name(row["paid_by"]))
            split_ids = [int(x) for x in row["split_ids"].split(",")]
            n = len(split_ids)
            debtors = [uid for uid in split_ids if uid != row["paid_by"]]
            settled = all((d, row["paid_by"]) not in outstanding for d in debtors)
            icon = "✅" if settled else "⏳"
            lines.append(
                f"{icon} #{row['id']} *{payer_name}* paid {currency}{row['amount']:.2f} _{esc(row['description'])}_ · {date} ({n} people)"
            )
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ #{row['id']} {row['description']} ({currency}{row['amount']:.2f})",
                    callback_data=f"del:{row['id']}",
                )
            ])
        else:
            fname = esc(name(row["from_user"]))
            tname = esc(name(row["to_user"]))
            lines.append(f"💸 *{fname}* paid *{tname}* {currency}{row['amount']:.2f} · {date}")

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
