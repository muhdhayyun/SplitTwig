import sqlite3
from pathlib import Path

DB_PATH = Path("data.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                name     TEXT,
                currency TEXT NOT NULL DEFAULT 'SGD'
            );
            CREATE TABLE IF NOT EXISTS members (
                user_id      INTEGER NOT NULL,
                group_id     INTEGER NOT NULL,
                username     TEXT,
                display_name TEXT,
                PRIMARY KEY (user_id, group_id)
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id    INTEGER NOT NULL,
                paid_by     INTEGER NOT NULL,
                amount      REAL    NOT NULL,
                description TEXT    NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS expense_splits (
                expense_id INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                share      REAL    NOT NULL,
                PRIMARY KEY (expense_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS settlements (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                from_user  INTEGER NOT NULL,
                to_user    INTEGER NOT NULL,
                amount     REAL    NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ── Members ────────────────────────────────────────────────────────────────────

def ensure_member(group_id: int, user_id: int, username: str, display_name: str):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO groups (group_id, name) VALUES (?, 'Group')",
            (group_id,),
        )
        c.execute(
            """INSERT INTO members (user_id, group_id, username, display_name)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, group_id) DO UPDATE SET
                   username     = excluded.username,
                   display_name = excluded.display_name""",
            (user_id, group_id, username, display_name),
        )
        # Merge any manual placeholder that matches this username (with or without @)
        if username:
            manual = c.execute(
                """SELECT user_id FROM members
                   WHERE group_id = ? AND user_id < 0
                   AND (LOWER(display_name) = LOWER(?) OR LOWER(display_name) = LOWER(?))""",
                (group_id, username, f"@{username}"),
            ).fetchone()
            if manual:
                old_id = manual["user_id"]
                c.execute("UPDATE expense_splits SET user_id = ? WHERE user_id = ?", (user_id, old_id))
                c.execute("UPDATE expenses SET paid_by = ? WHERE paid_by = ? AND group_id = ?", (user_id, old_id, group_id))
                c.execute("UPDATE settlements SET from_user = ? WHERE from_user = ? AND group_id = ?", (user_id, old_id, group_id))
                c.execute("UPDATE settlements SET to_user = ? WHERE to_user = ? AND group_id = ?", (user_id, old_id, group_id))
                c.execute("DELETE FROM members WHERE user_id = ? AND group_id = ?", (old_id, group_id))


def get_members(group_id: int) -> list:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM members WHERE group_id = ?", (group_id,)
        ).fetchall()


def add_manual_member(group_id: int, display_name: str) -> bool:
    """Add a member by name only. Returns False if name already exists."""
    with _conn() as c:
        existing = c.execute(
            "SELECT 1 FROM members WHERE group_id = ? AND LOWER(display_name) = LOWER(?)",
            (group_id, display_name),
        ).fetchone()
        if existing:
            return False
        # Use negative IDs for manual members so they never clash with Telegram user IDs
        row = c.execute(
            "SELECT MIN(user_id) AS min_id FROM members WHERE group_id = ?", (group_id,)
        ).fetchone()
        min_id = row["min_id"] if row["min_id"] is not None else 0
        new_id = min(min_id - 1, -1)
        c.execute(
            "INSERT INTO groups (group_id, name) VALUES (?, 'Group') ON CONFLICT DO NOTHING",
            (group_id,),
        )
        c.execute(
            "INSERT INTO members (user_id, group_id, username, display_name) VALUES (?, ?, '', ?)",
            (new_id, group_id, display_name),
        )
    return True


# ── Expenses ───────────────────────────────────────────────────────────────────

def add_expense(
    group_id: int,
    paid_by: int,
    amount: float,
    description: str,
    split_among: list[int],
) -> int:
    share = round(amount / len(split_among), 2)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO expenses (group_id, paid_by, amount, description) VALUES (?, ?, ?, ?)",
            (group_id, paid_by, amount, description),
        )
        expense_id = cur.lastrowid
        c.executemany(
            "INSERT INTO expense_splits (expense_id, user_id, share) VALUES (?, ?, ?)",
            [(expense_id, uid, share) for uid in split_among],
        )
    return expense_id


def get_recent_expenses(group_id: int, limit: int = 10) -> list:
    with _conn() as c:
        return c.execute(
            """SELECT e.id, e.paid_by, e.amount, e.description, e.created_at,
                      GROUP_CONCAT(es.user_id) AS split_ids
               FROM expenses e
               JOIN expense_splits es ON e.id = es.expense_id
               WHERE e.group_id = ?
               GROUP BY e.id
               ORDER BY e.created_at DESC
               LIMIT ?""",
            (group_id, limit),
        ).fetchall()


def delete_expense(expense_id: int, user_id: int, group_id: int) -> bool:
    with _conn() as c:
        row = c.execute(
            "SELECT paid_by FROM expenses WHERE id = ? AND group_id = ?",
            (expense_id, group_id),
        ).fetchone()
        if not row or row["paid_by"] != user_id:
            return False
        c.execute("DELETE FROM expense_splits WHERE expense_id = ?", (expense_id,))
        c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    return True


# ── Balances ───────────────────────────────────────────────────────────────────

def get_balances(group_id: int) -> tuple[dict, dict]:
    """Returns (balances dict, members dict). Positive balance = owed money."""
    with _conn() as c:
        members = {m["user_id"]: m for m in get_members(group_id)}
        balances = {uid: 0.0 for uid in members}

        rows = c.execute(
            """SELECT e.paid_by, es.user_id, es.share
               FROM expenses e
               JOIN expense_splits es ON e.id = es.expense_id
               WHERE e.group_id = ?""",
            (group_id,),
        ).fetchall()

        for row in rows:
            if row["user_id"] != row["paid_by"]:
                balances[row["paid_by"]] = balances.get(row["paid_by"], 0.0) + row["share"]
                balances[row["user_id"]] = balances.get(row["user_id"], 0.0) - row["share"]

        for s in c.execute(
            "SELECT * FROM settlements WHERE group_id = ?", (group_id,)
        ).fetchall():
            balances[s["from_user"]] = balances.get(s["from_user"], 0.0) + s["amount"]
            balances[s["to_user"]] = balances.get(s["to_user"], 0.0) - s["amount"]

    return balances, members


def get_expense_breakdown(group_id: int, debtor_id: int, creditor_id: int) -> tuple[list, list]:
    """Returns (forward, reverse) expense rows.
    forward: creditor paid, debtor participated (debtor owes).
    reverse: debtor paid, creditor participated (offsets the net)."""
    with _conn() as c:
        forward = c.execute(
            """SELECT e.description, es.share
               FROM expenses e
               JOIN expense_splits es ON e.id = es.expense_id
               WHERE e.group_id = ? AND e.paid_by = ? AND es.user_id = ?
               ORDER BY e.created_at ASC""",
            (group_id, creditor_id, debtor_id),
        ).fetchall()
        reverse = c.execute(
            """SELECT e.description, es.share
               FROM expenses e
               JOIN expense_splits es ON e.id = es.expense_id
               WHERE e.group_id = ? AND e.paid_by = ? AND es.user_id = ?
               ORDER BY e.created_at ASC""",
            (group_id, debtor_id, creditor_id),
        ).fetchall()
        return forward, reverse


def get_pairwise_debts(group_id: int) -> tuple[list[tuple], dict]:
    """Direct per-pair net debts without cross-party simplification.
    Returns ([(debtor_id, creditor_id, net_amount)], members_dict)."""
    with _conn() as c:
        members = {m["user_id"]: m for m in get_members(group_id)}
        pair: dict[tuple, float] = {}

        for row in c.execute(
            """SELECT e.paid_by, es.user_id, es.share
               FROM expenses e JOIN expense_splits es ON e.id = es.expense_id
               WHERE e.group_id = ?""",
            (group_id,),
        ).fetchall():
            if row["user_id"] != row["paid_by"]:
                k = (row["user_id"], row["paid_by"])
                pair[k] = pair.get(k, 0.0) + row["share"]

        for s in c.execute(
            "SELECT from_user, to_user, amount FROM settlements WHERE group_id = ?",
            (group_id,),
        ).fetchall():
            k = (s["from_user"], s["to_user"])
            pair[k] = pair.get(k, 0.0) - s["amount"]

        seen: set = set()
        result = []
        for a, b in list(pair):
            if (a, b) in seen or (b, a) in seen:
                continue
            seen.add((a, b))
            seen.add((b, a))
            net = pair.get((a, b), 0.0) - pair.get((b, a), 0.0)
            if net > 0.005:
                result.append((a, b, round(net, 2)))
            elif net < -0.005:
                result.append((b, a, round(-net, 2)))

        return result, members


def get_recent_settlements(group_id: int, limit: int = 10) -> list:
    with _conn() as c:
        return c.execute(
            """SELECT from_user, to_user, amount, created_at
               FROM settlements WHERE group_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (group_id, limit),
        ).fetchall()


def get_all_settlements(group_id: int) -> list:
    with _conn() as c:
        return c.execute(
            """SELECT from_user, to_user, amount, created_at
               FROM settlements WHERE group_id = ?
               ORDER BY created_at ASC""",
            (group_id,),
        ).fetchall()


def get_all_expenses_with_splits(group_id: int) -> list:
    """Returns every expense with its splits, oldest first.
    Each item: {id, paid_by, amount, description, splits: [{user_id, share}, ...]}"""
    with _conn() as c:
        expenses = c.execute(
            """SELECT id, paid_by, amount, description, created_at
               FROM expenses WHERE group_id = ?
               ORDER BY created_at ASC""",
            (group_id,),
        ).fetchall()
        result = []
        for e in expenses:
            splits = c.execute(
                "SELECT user_id, share FROM expense_splits WHERE expense_id = ?",
                (e["id"],),
            ).fetchall()
            result.append({
                "id": e["id"],
                "paid_by": e["paid_by"],
                "amount": e["amount"],
                "description": e["description"],
                "splits": [{"user_id": s["user_id"], "share": s["share"]} for s in splits],
            })
        return result


def get_settled_amount(group_id: int, from_user: int, to_user: int) -> float:
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(SUM(amount), 0.0) AS total FROM settlements WHERE group_id = ? AND from_user = ? AND to_user = ?",
            (group_id, from_user, to_user),
        ).fetchone()
        return row["total"] if row else 0.0


def simplify_debts(balances: dict) -> list[tuple]:
    """Greedy debt simplification. Returns [(debtor_id, creditor_id, amount)]."""
    creditors = sorted(
        [(uid, bal) for uid, bal in balances.items() if bal > 0.005],
        key=lambda x: x[1], reverse=True,
    )
    debtors = sorted(
        [(uid, -bal) for uid, bal in balances.items() if bal < -0.005],
        key=lambda x: x[1], reverse=True,
    )

    transactions = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]
        amount = round(min(debt, credit), 2)
        transactions.append((debtor_id, creditor_id, amount))
        debtors[i] = (debtor_id, round(debt - amount, 10))
        creditors[j] = (creditor_id, round(credit - amount, 10))
        if debtors[i][1] < 0.005:
            i += 1
        if creditors[j][1] < 0.005:
            j += 1

    return transactions


# ── Settlements ────────────────────────────────────────────────────────────────

def add_settlement(group_id: int, from_user: int, to_user: int, amount: float):
    with _conn() as c:
        c.execute(
            "INSERT INTO settlements (group_id, from_user, to_user, amount) VALUES (?, ?, ?, ?)",
            (group_id, from_user, to_user, amount),
        )


# ── Currency ───────────────────────────────────────────────────────────────────

def get_currency(group_id: int) -> str:
    with _conn() as c:
        row = c.execute(
            "SELECT currency FROM groups WHERE group_id = ?", (group_id,)
        ).fetchone()
        return row["currency"] if row else "SGD"


def set_currency(group_id: int, currency: str):
    with _conn() as c:
        c.execute(
            """INSERT INTO groups (group_id, currency) VALUES (?, ?)
               ON CONFLICT(group_id) DO UPDATE SET currency = excluded.currency""",
            (group_id, currency),
        )
