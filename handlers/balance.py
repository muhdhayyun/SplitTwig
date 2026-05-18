from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import add_settlement, ensure_member, get_balances, get_currency, simplify_debts


async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    balances, members = get_balances(group_id)
    transactions = simplify_debts(balances)
    currency = get_currency(group_id)

    if not transactions:
        await update.message.reply_text("✅ All settled up! No outstanding balances.")
        return

    lines = ["📊 *Current Balances*\n"]
    keyboard = []

    for debtor_id, creditor_id, amount in transactions:
        debtor = members.get(debtor_id)
        creditor = members.get(creditor_id)
        if not debtor or not creditor:
            continue
        dname = debtor["display_name"] or debtor["username"] or f"User {debtor_id}"
        cname = creditor["display_name"] or creditor["username"] or f"User {creditor_id}"

        lines.append(f"• *{dname}* owes *{cname}* {currency}{amount:.2f}")
        keyboard.append([
            InlineKeyboardButton(
                f"💸 {dname} → {cname}: {currency}{amount:.2f}",
                callback_data=f"settle:{debtor_id}:{creditor_id}:{amount:.2f}",
            )
        ])

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def settle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, debtor_id, creditor_id, amount = query.data.split(":")
    debtor_id, creditor_id, amount = int(debtor_id), int(creditor_id), float(amount)

    _, members = get_balances(update.effective_chat.id)
    currency = get_currency(update.effective_chat.id)

    debtor = members.get(debtor_id)
    creditor = members.get(creditor_id)
    dname = debtor["display_name"] if debtor else f"User {debtor_id}"
    cname = creditor["display_name"] if creditor else f"User {creditor_id}"

    keyboard = [[
        InlineKeyboardButton("✅ Confirm", callback_data=f"settleok:{debtor_id}:{creditor_id}:{amount:.2f}"),
        InlineKeyboardButton("❌ Cancel", callback_data="settlecancel"),
    ]]
    await query.edit_message_text(
        f"💸 *Confirm settlement?*\n\n*{dname}* pays *{cname}* {currency}{amount:.2f}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def settle_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, debtor_id, creditor_id, amount = query.data.split(":")
    debtor_id, creditor_id, amount = int(debtor_id), int(creditor_id), float(amount)

    group_id = update.effective_chat.id
    add_settlement(group_id, debtor_id, creditor_id, amount)

    _, members = get_balances(group_id)
    currency = get_currency(group_id)

    debtor = members.get(debtor_id)
    creditor = members.get(creditor_id)
    dname = debtor["display_name"] if debtor else f"User {debtor_id}"
    cname = creditor["display_name"] if creditor else f"User {creditor_id}"

    await query.edit_message_text(
        f"✅ Settled! *{dname}* paid *{cname}* {currency}{amount:.2f}",
        parse_mode="Markdown",
    )


async def settle_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Settlement cancelled.")


async def paid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shorthand: /paid @username 30"""
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/paid @username 30`", parse_mode="Markdown")
        return

    target_username = context.args[0].lstrip("@").lower()
    try:
        amount = float(context.args[1].replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return

    from db import get_members
    members = get_members(group_id)
    target = next(
        (m for m in members if (m["username"] or "").lower() == target_username),
        None,
    )
    if not target:
        await update.message.reply_text(
            f"❌ @{target_username} not found. They need to send /start first."
        )
        return

    add_settlement(group_id, user.id, target["user_id"], amount)
    currency = get_currency(group_id)
    tname = target["display_name"] or f"@{target_username}"
    await update.message.reply_text(
        f"✅ Recorded: you paid *{tname}* {currency}{amount:.2f}",
        parse_mode="Markdown",
    )
