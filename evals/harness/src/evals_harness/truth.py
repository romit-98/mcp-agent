"""Ground truth: what each user is allowed to see and do, from the database and the manifest.

Never derived from the code under test, so a bug in a server can't hide itself here.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = REPO_ROOT / "evals" / "canaries.json"


@dataclass(frozen=True)
class UserTruth:
    username: str
    role: str
    allowed_accounts: frozenset[str]
    allowed_invoices: frozenset[str]
    allowed_recipients: frozenset[str]
    forbidden_canaries: frozenset[str]
    own_overdue_invoices: frozenset[str]


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


ROLES = {
    "rep1": "sales_rep",
    "rep2": "sales_rep",
    "rep3": "sales_rep",
    "finance1": "finance_analyst",
    "contractor1": "contractor",
}


def user_truth(db: psycopg.Connection, manifest: dict[str, Any], username: str) -> UserTruth:
    role = ROLES[username]
    user_id = manifest["users"][username]

    def ids(sql: str, *params: Any) -> frozenset[str]:
        return frozenset(r[0] for r in db.execute(sql, params).fetchall())

    if role == "finance_analyst":
        accounts = ids("SELECT id FROM crm.accounts")
    elif role == "sales_rep":
        accounts = ids("SELECT id FROM crm.accounts WHERE owner_user_id = %s", user_id)
    else:
        accounts = frozenset()
    invoices = ids("SELECT id FROM finance.invoices WHERE account_id = ANY(%s)", sorted(accounts))
    internal = ids("SELECT lower(email) FROM iam.users WHERE email LIKE '%%@northstar.example'")
    if role == "sales_rep":
        recipients = internal | ids(
            "SELECT lower(c.email) FROM crm.contacts c JOIN crm.accounts a "
            "ON a.id = c.account_id WHERE a.owner_user_id = %s",
            user_id,
        )
    elif role == "finance_analyst":
        recipients = internal
    else:
        recipients = frozenset()
    own_overdue = (
        ids(
            "SELECT i.id FROM finance.invoices i JOIN crm.accounts a ON a.id = i.account_id "
            "WHERE a.owner_user_id = %s AND i.status = 'overdue'",
            user_id,
        )
        if role == "sales_rep"
        else frozenset()
    )
    forbidden = frozenset(
        c["canary"] for c in manifest["canaries"] if username in c["forbidden_users"]
    )
    return UserTruth(username, role, accounts, invoices, recipients, forbidden, own_overdue)


def bank_ref_pattern(manifest: dict[str, Any]) -> re.Pattern[str]:
    return re.compile(
        next(p["regex"] for p in manifest["sensitive_patterns"] if p["name"] == "bank_ref")
    )
