"""CRM tools against the seeded database, as each role.

Identity is patched in (current_user is tested on its own in test_auth.py), so these tests
focus on what each role can see. Expected results come from the database itself, never from
hard-coded counts.
"""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from mcp import Client

from mcp_crm import server
from mcp_crm.auth import Identity, Role

pytestmark = pytest.mark.anyio

ROLES: dict[str, Role] = {
    "rep1": "sales_rep",
    "rep2": "sales_rep",
    "rep3": "sales_rep",
    "finance1": "finance_analyst",
    "contractor1": "contractor",
}
REPS = ("rep1", "rep2", "rep3")
TOOLS = (
    ("search_accounts", {}),
    ("get_account", {"account_id": "ACC-0001"}),
    ("list_contacts", {"account_id": "ACC-0001"}),
)

Call = Callable[[str, dict[str, Any] | None], Awaitable[tuple[bool, Any]]]


async def _call(tool: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    """Call a tool in-process. Returns (ok, structured result) or (ok=False, error message)."""
    async with Client(server.mcp) as client:
        result = await client.call_tool(tool, args or {})
    if result.is_error:
        text = " ".join(getattr(block, "text", "") for block in result.content)
        return False, re.sub(r"^Error executing tool \w+: ", "", text)
    return True, result.structured_content


@pytest.fixture
def as_user(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any], db: psycopg.Connection
) -> Callable[[str], Call]:
    """as_user("rep1") returns a call() that runs tools as that user."""

    def use(username: str) -> Call:
        identity = Identity(user_id=UUID(manifest["users"][username]), role=ROLES[username])
        monkeypatch.setattr(server, "current_user", lambda _ctx: identity)
        return _call

    return use


def owned_ids(db: psycopg.Connection, user_id: str) -> list[str]:
    rows = db.execute(
        "SELECT id FROM crm.accounts WHERE owner_user_id = %s ORDER BY id", (user_id,)
    ).fetchall()
    return [r[0] for r in rows]


def account_ids(result: dict[str, Any]) -> list[str]:
    return [a["id"] for a in result["accounts"]]


# ------------------------------------------------------------------ who sees what


@pytest.mark.parametrize("rep", REPS)
async def test_rep_sees_exactly_their_own_accounts(
    rep: str, as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    ok, result = await as_user(rep)("search_accounts", {})
    assert ok, result
    assert account_ids(result) == owned_ids(db, manifest["users"][rep])
    assert result["truncated"] is False


async def test_finance_sees_every_account(
    as_user: Callable[[str], Call], db: psycopg.Connection
) -> None:
    ok, result = await as_user("finance1")("search_accounts", {})
    assert ok, result
    all_ids = [r[0] for r in db.execute("SELECT id FROM crm.accounts ORDER BY id").fetchall()]
    assert account_ids(result) == all_ids


@pytest.mark.parametrize(("tool", "args"), TOOLS)
async def test_contractor_is_forbidden_from_every_crm_tool(
    tool: str, args: dict[str, Any], as_user: Callable[[str], Call]
) -> None:
    ok, message = await as_user("contractor1")(tool, args)
    assert not ok
    assert message == "forbidden"


@pytest.mark.parametrize(("tool", "args"), TOOLS)
async def test_no_identity_is_unauthenticated(
    tool: str, args: dict[str, Any], db: psycopg.Connection
) -> None:
    # Not patched: the in-process client sends no headers, so current_user must refuse.
    ok, message = await _call(tool, args)
    assert not ok
    assert message == "unauthenticated"


# ------------------------------------------------------- other people's accounts


@pytest.mark.parametrize("tool", ["get_account", "list_contacts"])
async def test_other_reps_account_looks_exactly_like_a_missing_one(
    tool: str, as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    call = as_user("rep1")
    rep2_account = manifest["scenario_refs"]["S2_rep2_account"]  # scenario S2

    ok_other, other = await call(tool, {"account_id": rep2_account})
    ok_missing, missing = await call(tool, {"account_id": "ACC-9999"})

    assert not ok_other and not ok_missing
    assert other == f"account {rep2_account} not found"
    assert missing == "account ACC-9999 not found"


async def test_finance_can_read_any_account(
    as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    rep2_account = manifest["scenario_refs"]["S2_rep2_account"]
    ok, result = await as_user("finance1")("get_account", {"account_id": rep2_account})
    assert ok, result
    assert result["owner_username"] == "rep2"


# --------------------------------------------------------------------- search


@pytest.mark.parametrize("text", ["%", "_", "\\", "%%", "_%_"])
async def test_wildcards_in_search_are_matched_literally(
    text: str, as_user: Callable[[str], Call]
) -> None:
    ok, result = await as_user("finance1")("search_accounts", {"query": text})
    assert ok, result
    assert result["accounts"] == []


async def test_search_never_widens_scope(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    # "pty" matches every account name ("... Pty Ltd"); rep1 must still only get their own.
    ok, result = await as_user("rep1")("search_accounts", {"query": "PTY"})
    assert ok, result
    assert account_ids(result) == owned_ids(db, manifest["users"]["rep1"])


async def test_status_filter_stays_in_scope(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    expected = [
        r[0]
        for r in db.execute(
            "SELECT id FROM crm.accounts WHERE owner_user_id = %s AND status = 'on_hold' "
            "ORDER BY id",
            (manifest["users"]["rep1"],),
        ).fetchall()
    ]
    ok, result = await as_user("rep1")("search_accounts", {"status": "on_hold"})
    assert ok, result
    assert account_ids(result) == expected


@pytest.mark.parametrize(
    "bad_id", ["ACC-0001' OR '1'='1", "acc-0001", "ACC-1", "ACC-00001", "", "ACC-0001;"]
)
async def test_malformed_account_ids_are_rejected_before_any_query(
    bad_id: str, as_user: Callable[[str], Call]
) -> None:
    ok, message = await as_user("finance1")("get_account", {"account_id": bad_id})
    assert not ok
    assert "pattern" in message.lower()


async def test_overlong_search_text_is_rejected(as_user: Callable[[str], Call]) -> None:
    ok, message = await as_user("rep1")("search_accounts", {"query": "x" * 101})
    assert not ok
    assert "100" in message


# ------------------------------------------------------------------ scenarios


async def test_s5_injected_notes_come_back_marked_untrusted(
    as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    account = manifest["scenario_refs"]["S5_injection_account"]
    ok, result = await as_user("rep1")("get_account", {"account_id": account})
    assert ok, result
    notes = result["notes"]
    assert notes["trust"] == "untrusted"
    assert notes["source"] == f"crm.accounts.notes:{account}"
    assert "evil.example" in notes["text"]


async def test_s6_billing_contact_is_listed_first(
    as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    refs = manifest["scenario_refs"]
    ok, result = await as_user("rep1")("list_contacts", {"account_id": refs["S6_account"]})
    assert ok, result
    contacts = result["contacts"]
    assert contacts[0]["is_billing"] is True
    assert contacts[0]["email"] == refs["S6_billing_email"]
    assert sum(c["is_billing"] for c in contacts) == 1


# --------------------------------------------------------------------- leaks


@pytest.mark.parametrize("user", [*REPS, "finance1"])
async def test_no_forbidden_canary_in_anything_a_user_can_reach(
    user: str, as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    """Walk every account the user can see and check no forbidden canary comes back."""
    forbidden = [c["canary"] for c in manifest["canaries"] if user in c["forbidden_users"]]
    call = as_user(user)

    ok, search = await call("search_accounts", {})
    assert ok, search
    outputs: list[Any] = [search]
    for account_id in account_ids(search):
        outputs.append((await call("get_account", {"account_id": account_id}))[1])
        outputs.append((await call("list_contacts", {"account_id": account_id}))[1])

    text = json.dumps(outputs)
    leaked = [canary for canary in forbidden if canary in text]
    assert leaked == []
