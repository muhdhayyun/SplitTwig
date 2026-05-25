from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from db import (
    add_settlement,
    ensure_member,
    get_all_expenses_with_splits,
    get_all_settlements,
    get_currency,
    get_members,
)


def esc(text: str) -> str:
    for ch in ("_", "*", "[", "`"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _name(member: dict, uid: int) -> str:
    if not member:
        return f"User {uid}"
    name = member["display_name"] or member["username"] or f"User {uid}"
    # Strip leading @ so Telegram doesn't fire a mention notification
    return name.lstrip("@")


async def balance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = update.effective_chat.id
    ensure_member(group_id, user.id, user.username or "", user.full_name)

    members = {m["user_id"]: m for m in get_members(group_id)}
    currency = get_currency(group_id)

    # Optional filter: /balance @username
    filter_uid = None
    if context.args:
        target = context.args[0].lstrip("@").lower()
        for uid, m in members.items():
            uname = (m["username"] or "").lower()
            dname = (m["display_name"] or "").lower()
            if target and (uname == target or dname == target or dname == f"@{target}"):
                filter_uid = uid
                break
        if filter_uid is None:
            await update.message.reply_text(f"❌ User '{context.args[0]}' not found.")
            return

    expenses = get_all_expenses_with_splits(group_id)
    settlements = get_all_settlements(group_id)

    # Group expenses by payer
    by_payer: dict[int, list] = {}
    for e in expenses:
        by_payer.setdefault(e["paid_by"], []).append(e)

    payer_ids = [filter_uid] if filter_uid is not None else list(members.keys())

    lines = ["📊 *Group Balances*"]
    for uid in payer_ids:
        member = members.get(uid)
        if not member:
            continue
        name = esc(_name(member, uid))
        payer_expenses = by_payer.get(uid, [])

        if not payer_expenses:
            lines.append(f"\n💰 *{name}*: — no payments made —")
            continue

        lines.append(f"\n💰 *{name}* paid:")

        # Group every split this payer is owed for, keyed by debtor (oldest first)
        debtor_items: dict[int, list] = {}
        debtor_order: list[int] = []
        for exp in payer_expenses:
            for split in exp["splits"]:
                if split["user_id"] == uid:
                    continue
                did = split["user_id"]
                if did not in debtor_items:
                    debtor_items[did] = []
                    debtor_order.append(did)
                debtor_items[did].append({
                    "share": split["share"],
                    "description": exp["description"],
                })

        for did in debtor_order:
            debtor = members.get(did)
            dname = esc(_name(debtor, did))
            items = debtor_items[did]
            total = sum(item["share"] for item in items)
            lines.append(f"  • *{dname}* owes {currency}{total:.2f}")
            for item in items:
                lines.append(f"      ↳ {currency}{item['share']:.2f} — {esc(item['description'])}")

    if settlements and filter_uid is None:
        lines.append("\n💸 *Settlements:*")
        for s in settlements:
            from_name = esc(_name(members.get(s["from_user"]), s["from_user"]))
            to_name = esc(_name(members.get(s["to_user"]), s["to_user"]))
            lines.append(f"  • {from_name} paid {to_name} {currency}{s['amount']:.2f}")

    if filter_uid is None:
        expense_totals: dict[tuple[int, int], float] = {}
        for e in expenses:
            payer = e["paid_by"]
            for split in e["splits"]:
                if split["user_id"] == payer:
                    continue
                key = (split["user_id"], payer)
                expense_totals[key] = expense_totals.get(key, 0.0) + split["share"]

        settlement_totals: dict[tuple[int, int], float] = {}
        for s in settlements:
            key = (s["from_user"], s["to_user"])
            settlement_totals[key] = settlement_totals.get(key, 0.0) + s["amount"]

        # Net each pair: net A→B = (exp_ab − paid_ab) − (exp_ba − paid_ba)
        netted: list[dict] = []
        seen: set[frozenset] = set()
        for a, b in set(expense_totals.keys()) | set(settlement_totals.keys()):
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            exp_ab = expense_totals.get((a, b), 0.0)
            exp_ba = expense_totals.get((b, a), 0.0)
            paid_ab = settlement_totals.get((a, b), 0.0)
            paid_ba = settlement_totals.get((b, a), 0.0)
            net = exp_ab - paid_ab - exp_ba + paid_ba
            if abs(net) < 0.005:
                continue
            if net > 0:
                netted.append({
                    "debtor": a, "creditor": b, "amount": round(net, 2),
                    "raw_dc": exp_ab, "paid_dc": paid_ab,
                    "raw_cd": exp_ba, "paid_cd": paid_ba,
                })
            else:
                netted.append({
                    "debtor": b, "creditor": a, "amount": round(-net, 2),
                    "raw_dc": exp_ba, "paid_dc": paid_ba,
                    "raw_cd": exp_ab, "paid_cd": paid_ab,
                })

        if netted:
            lines.append("\n🧮 *Cumulative* _(after settlements, netted per pair)_:")
            netted.sort(key=lambda t: (
                _name(members.get(t["creditor"]), t["creditor"]).lower(),
                _name(members.get(t["debtor"]), t["debtor"]).lower(),
            ))
            for item in netted:
                dname = esc(_name(members.get(item["debtor"]), item["debtor"]))
                cname = esc(_name(members.get(item["creditor"]), item["creditor"]))
                lines.append(f"  • *{dname}* owes *{cname}* {currency}{item['amount']:.2f}")

                # Show the math only when there's more than one component
                components = [
                    (item["raw_dc"],  f"+", f"expenses, {dname}→{cname}"),
                    (item["paid_dc"], f"−", f"{dname} paid {cname}"),
                    (item["raw_cd"],  f"−", f"expenses, {cname}→{dname}"),
                    (item["paid_cd"], f"+", f"{cname} paid {dname}"),
                ]
                nonzero = [(v, sign, label) for v, sign, label in components if v > 0.005]
                if len(nonzero) > 1:
                    for v, sign, label in nonzero:
                        lines.append(f"      ↳ {sign}{currency}{v:.2f} _({label})_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def settle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, debtor_id, creditor_id, amount = query.data.split(":")
    debtor_id, creditor_id, amount = int(debtor_id), int(creditor_id), float(amount)

    members = {m["user_id"]: m for m in get_members(update.effective_chat.id)}
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

    members = {m["user_id"]: m for m in get_members(group_id)}
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
