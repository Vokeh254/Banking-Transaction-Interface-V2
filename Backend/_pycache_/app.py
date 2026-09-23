"""
Simple Banking Transaction Interface — backend
------------------------------------------------
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "banking.db")

# An account with no deposits/withdrawals/transfers for this many days
# is considered dormant and becomes eligible for deletion.
# (Lowered to a small number here would let you test deletion quickly —
#  e.g. set it to 0 temporarily while testing, then put it back to 90.)
DORMANCY_DAYS = 90

app = Flask(__name__)
CORS(app)  # allows the frontend (opened as a local file) to call this API


# ---------- Database helpers ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            balance REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_activity_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            principal REAL NOT NULL,
            disbursed_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            FOREIGN KEY (account_id) REFERENCES accounts (id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            related_account_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts (id)
        )
    """)
    conn.commit()
    conn.close()


def touch_account(conn, account_id):
    """Marks an account as 'just used' — resets the dormancy clock."""
    conn.execute(
        "UPDATE accounts SET last_activity_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), account_id),
    )


def log_transaction(conn, account_id, tx_type, amount, related_account_id=None):
    conn.execute(
        """INSERT INTO transactions (account_id, type, amount, related_account_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (account_id, tx_type, amount, related_account_id, datetime.utcnow().isoformat()),
    )


def is_dormant(account_row):
    last = datetime.fromisoformat(account_row["last_activity_at"])
    return (datetime.utcnow() - last) > timedelta(days=DORMANCY_DAYS)


def account_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "balance": round(row["balance"], 2),
        "created_at": row["created_at"],
        "last_activity_at": row["last_activity_at"],
        "dormant": is_dormant(row),
    }


def get_account_or_none(conn, account_id):
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


# ---------- Routes ----------

@app.route("/api/accounts", methods=["GET"])
def list_accounts():
    conn = get_db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    conn.close()
    return jsonify([account_to_dict(r) for r in rows])


@app.route("/api/accounts", methods=["POST"])
def create_account():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    try:
        initial_deposit = float(data.get("initial_deposit", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Initial deposit must be a number"}), 400

    if not name:
        return jsonify({"error": "Account holder name is required"}), 400
    if initial_deposit < 0:
        return jsonify({"error": "Initial deposit cannot be negative"}), 400

    conn = get_db()
    now = datetime.utcnow().isoformat()
    cur = conn.execute(
        "INSERT INTO accounts (name, balance, created_at, last_activity_at) VALUES (?, ?, ?, ?)",
        (name, initial_deposit, now, now),
    )
    account_id = cur.lastrowid
    if initial_deposit > 0:
        log_transaction(conn, account_id, "deposit", initial_deposit)
    conn.commit()
    row = get_account_or_none(conn, account_id)
    conn.close()
    return jsonify(account_to_dict(row)), 201


@app.route("/api/accounts/<int:account_id>/deposit", methods=["POST"])
def deposit(account_id):
    data = request.get_json(force=True) or {}
    try:
        amount = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "Deposit amount must be positive"}), 400

    conn = get_db()
    row = get_account_or_none(conn, account_id)
    if row is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404

    conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, account_id))
    touch_account(conn, account_id)
    log_transaction(conn, account_id, "deposit", amount)
    conn.commit()
    row = get_account_or_none(conn, account_id)
    conn.close()
    return jsonify(account_to_dict(row))


@app.route("/api/accounts/<int:account_id>/withdraw", methods=["POST"])
def withdraw(account_id):
    data = request.get_json(force=True) or {}
    try:
        amount = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "Withdrawal amount must be positive"}), 400

    conn = get_db()
    row = get_account_or_none(conn, account_id)
    if row is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404
    if row["balance"] < amount:
        conn.close()
        return jsonify({"error": "Insufficient funds"}), 400

    conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, account_id))
    touch_account(conn, account_id)
    log_transaction(conn, account_id, "withdraw", amount)
    conn.commit()
    row = get_account_or_none(conn, account_id)
    conn.close()
    return jsonify(account_to_dict(row))


@app.route("/api/transfer", methods=["POST"])
def transfer():
    data = request.get_json(force=True) or {}
    from_id = data.get("from_id")
    to_id = data.get("to_id")
    try:
        amount = float(data.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "Amount must be a number"}), 400

    if not from_id or not to_id:
        return jsonify({"error": "Both accounts are required"}), 400
    if int(from_id) == int(to_id):
        return jsonify({"error": "Cannot transfer to the same account"}), 400
    if amount <= 0:
        return jsonify({"error": "Transfer amount must be positive"}), 400

    conn = get_db()
    from_row = get_account_or_none(conn, from_id)
    to_row = get_account_or_none(conn, to_id)
    if from_row is None or to_row is None:
        conn.close()
        return jsonify({"error": "One or both accounts were not found"}), 404
    if from_row["balance"] < amount:
        conn.close()
        return jsonify({"error": "Insufficient funds in source account"}), 400

    conn.execute("UPDATE accounts SET balance = balance - ? WHERE id = ?", (amount, from_id))
    conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (amount, to_id))
    touch_account(conn, from_id)
    touch_account(conn, to_id)
    log_transaction(conn, from_id, "transfer_out", amount, related_account_id=to_id)
    log_transaction(conn, to_id, "transfer_in", amount, related_account_id=from_id)
    conn.commit()
    conn.close()
    return jsonify({"message": f"Transferred KES {amount:,.2f} from account {from_id} to account {to_id}"})


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
def delete_account(account_id):
    conn = get_db()
    row = get_account_or_none(conn, account_id)
    if row is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404
    if not is_dormant(row):
        conn.close()
        return jsonify({
            "error": f"Account is still active — only accounts inactive for "
                     f"{DORMANCY_DAYS}+ days can be deleted"
        }), 400

    conn.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
    conn.execute("DELETE FROM loans WHERE account_id = ?", (account_id,))
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": f"Dormant account {account_id} deleted"})


@app.route("/api/accounts/<int:account_id>/loan", methods=["POST"])
def disburse_loan(account_id):
    """Bonus feature: opens a loan for the account and credits 10,000 KES."""
    conn = get_db()
    row = get_account_or_none(conn, account_id)
    if row is None:
        conn.close()
        return jsonify({"error": "Account not found"}), 404

    principal = 10000.0
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO loans (account_id, principal, disbursed_at, status) VALUES (?, ?, ?, ?)",
        (account_id, principal, now, "active"),
    )
    conn.execute("UPDATE accounts SET balance = balance + ? WHERE id = ?", (principal, account_id))
    touch_account(conn, account_id)
    log_transaction(conn, account_id, "loan_disbursement", principal)
    conn.commit()
    acc_row = get_account_or_none(conn, account_id)
    conn.close()
    return jsonify({
        "message": "KES 10,000 loan disbursed successfully",
        "account": account_to_dict(acc_row),
    })


@app.route("/api/accounts/<int:account_id>/transactions", methods=["GET"])
def account_transactions(account_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE account_id = ? ORDER BY id DESC", (account_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
    app.run(debug=True, port=5000)
