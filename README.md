# Simple Banking Transaction Interface

A minimal full-stack banking demo:
- **Backend:** Python (Flask) + SQLite — all money logic and storage
- **Frontend:** HTML + CSS + JavaScript — talks to the backend over HTTP

## How to run

### 1. Start the backend
```bash
cd backend
pip install -r requirements.txt
python app.py
```
This starts the API at `http://127.0.0.1:5000` and creates `banking.db` automatically the first time you run it.

### 2. Open the frontend
Just open `frontend/index.html` directly in your browser (double-click it, or
right-click → Open With → your browser). It will talk to the backend
automatically as long as `app.py` is running.

## What each part does

| File | Role |
|---|---|
| `backend/app.py` | REST API: create/deposit/withdraw/transfer/delete accounts, disburse loans |
| `backend/banking.db` | Auto-created SQLite database (accounts, transactions, loans tables) |
| `frontend/index.html` | Page structure — one form per operation |
| `frontend/style.css` | Visual styling |
| `frontend/script.js` | Sends fetch() requests to the backend and updates the page |

## Notes on the design choices

- **Dormancy rule:** an account can only be deleted if it's had no activity
  for 90+ days (see `DORMANCY_DAYS` in `app.py`). To test deletion without
  waiting, temporarily set that constant to `0`, restart the backend, delete
  the test account, then set it back to `90`.
- **Transfers are atomic in effect:** both the debit and credit happen in the
  same request, so you never end up with money missing from one account and
  not yet in the other.
- **Every operation is logged** to the `transactions` table, which is also
  what dormancy is calculated from.
- **The loan feature** opens a row in `loans` and credits the account
  balance directly — a simplified stand-in for a real disbursement process.

## Extending it further (ideas, not required)
- Add loan repayment endpoints and interest calculation
- Add authentication (right now anyone can act on any account ID)
- Show a transaction history view per account (the API endpoint
  `/api/accounts/<id>/transactions` already exists for this)
