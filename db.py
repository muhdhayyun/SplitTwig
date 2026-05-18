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
                currency TEXT NOT NULL DEFAULT 'USD'
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


def get_members(group_id: int) -> list:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM members WHERE group_id = ?", (group_id,)
        ).fetchall()


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
        return row["currency"] if row else "USD"


def set_currency(group_id: int, currency: str):
    with _conn() as c:
        c.execute(
            """INSERT INTO groups (group_id, currency) VALUES (?, ?)
               ON CONFLICT(group_id) DO UPDATE SET currency = excluded.currency""",
            (group_id, currency),
        )
