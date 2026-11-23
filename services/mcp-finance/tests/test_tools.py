"""Finance tools against the seeded database, as each role.

Identity is patched in (current_user is tested in libs/northstar-common), so these tests focus
on what each role can see and do. Expected results come from the database itself.
"""

import json
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from mcp import Client

from mcp_finance import server
from mcp_finance.auth import Identity, Role

pytestmark = pytest.mark.anyio

ROLES: dict[str, Role] = {
    "rep1": "sales_rep",
    "rep2": "sales_rep",
    "rep3": "sales_rep",
    "finance1": "finance_analyst",
    "contractor1": "contractor",
}
REPS = ("rep1", "rep2", "rep3")
READ_TOOLS = (
    ("list_invoices", {}),
    ("get_invoice", {"invoice_id": "INV-1001"}),
)
DRAFT = "draft_credit_note"

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


def ids(rows: list[tuple[Any, ...]]) -> list[str]:
    return [r[0] for r in rows]


def invoices_of(db: psycopg.Connection, user_id: str, extra: str = "", *args: Any) -> list[str]:
    """Ground truth: invoice IDs on accounts the user owns."""
    sql = (
        "SELECT i.id FROM finance.invoices i JOIN crm.accounts a ON a.id = i.account_id "
        f"WHERE a.owner_user_id = %s {extra} ORDER BY i.id"
    )
    return ids(db.execute(sql, (user_id, *args)).fetchall())


def rep_account(db: psycopg.Connection, user_id: str) -> str:
    return db.execute(
        "SELECT id FROM crm.accounts WHERE owner_user_id = %s ORDER BY id LIMIT 1", (user_id,)
    ).fetchone()[0]


def rep_invoice(db: psycopg.Connection, user_id: str) -> str:
    return invoices_of(db, user_id)[0]


# ----------------------------------------------------------------- who sees what


@pytest.mark.parametrize("rep", REPS)
async def test_rep_lists_only_invoices_on_their_own_accounts(
    rep: str, as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    owned = invoices_of(db, manifest["users"][rep])
    ok, result = await as_user(rep)("list_invoices", {})
    assert ok, result
    returned = [i["id"] for i in result["invoices"]]
    assert returned == owned[: server.LIST_LIMIT]
    assert result["truncated"] is (len(owned) > server.LIST_LIMIT)


@pytest.mark.parametrize("rep", REPS)
async def test_rep_overdue_filter_matches_the_database(
    rep: str, as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    expected = invoices_of(db, manifest["users"][rep], "AND i.status = %s", "overdue")
    ok, result = await as_user(rep)("list_invoices", {"status": "overdue"})
    assert ok, result
    assert [i["id"] for i in result["invoices"]] == expected
    assert expected, "seed guarantees every rep has overdue invoices (scenario S1)"


async def test_rep_can_list_one_of_their_accounts(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    rep1 = manifest["users"]["rep1"]
    account = rep_account(db, rep1)
    expected = invoices_of(db, rep1, "AND i.account_id = %s", account)
    ok, result = await as_user("rep1")("list_invoices", {"account_id": account})
    assert ok, result
    assert [i["id"] for i in result["invoices"]] == expected


async def test_finance_sees_invoices_on_every_account(
    as_user: Callable[[str], Call], db: psycopg.Connection
) -> None:
    all_ids = ids(db.execute("SELECT id FROM finance.invoices ORDER BY id").fetchall())
    ok, result = await as_user("finance1")("list_invoices", {})
    assert ok, result
    assert [i["id"] for i in result["invoices"]] == all_ids[: server.LIST_LIMIT]
    assert result["truncated"] is True  # 500 invoices, capped at 100


@pytest.mark.parametrize(("tool", "args"), [*READ_TOOLS, (DRAFT, {})])
async def test_contractor_is_forbidden(
    tool: str, args: dict[str, Any], as_user: Callable[[str], Call]
) -> None:
    if tool == DRAFT:
        args = {"invoice_id": "INV-1001", "amount": "10", "reason": "pytest: contractor"}
    ok, message = await as_user("contractor1")(tool, args)
    assert not ok
    assert message.startswith("forbidden")


@pytest.mark.parametrize(("tool", "args"), READ_TOOLS)
async def test_no_identity_is_unauthenticated(
    tool: str, args: dict[str, Any], db: psycopg.Connection
) -> None:
    ok, message = await _call(tool, args)
    assert not ok
    assert message == "unauthenticated"


# ------------------------------------------------------- other people's invoices


async def test_other_reps_invoice_looks_exactly_like_a_missing_one(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    rep2_invoice = rep_invoice(db, manifest["users"]["rep2"])
    call = as_user("rep1")
    ok_other, other = await call("get_invoice", {"invoice_id": rep2_invoice})
    ok_missing, missing = await call("get_invoice", {"invoice_id": "INV-9999"})
    assert not ok_other and not ok_missing
    assert other == f"invoice {rep2_invoice} not found"
    assert missing == "invoice INV-9999 not found"


async def test_s2_listing_another_reps_account_looks_like_a_missing_account(
    as_user: Callable[[str], Call], manifest: dict[str, Any]
) -> None:
    rep2_account = manifest["scenario_refs"]["S2_rep2_account"]
    call = as_user("rep1")
    ok_other, other = await call("list_invoices", {"account_id": rep2_account})
    ok_missing, missing = await call("list_invoices", {"account_id": "ACC-9999"})
    assert not ok_other and not ok_missing
    assert other == f"account {rep2_account} not found"
    assert missing == "account ACC-9999 not found"


async def test_rep_gets_full_detail_of_their_own_invoice(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    invoice_id = rep_invoice(db, manifest["users"]["rep1"])
    stored = db.execute(
        "SELECT amount, bank_ref FROM finance.invoices WHERE id = %s", (invoice_id,)
    ).fetchone()
    ok, result = await as_user("rep1")("get_invoice", {"invoice_id": invoice_id})
    assert ok, result
    assert Decimal(result["amount"]) == stored[0]
    # Returned as stored on purpose: the gateway redacts it in phase 6.
    assert result["bank_ref"] == stored[1]


@pytest.mark.parametrize("bad_id", ["INV-1", "inv-1001", "INV-1001' OR '1'='1", "ACC-0001", ""])
async def test_malformed_invoice_ids_are_rejected(
    bad_id: str, as_user: Callable[[str], Call]
) -> None:
    ok, message = await as_user("finance1")("get_invoice", {"invoice_id": bad_id})
    assert not ok
    assert "pattern" in message.lower()


# ------------------------------------------------------------- credit notes


def credit_notes_on(db: psycopg.Connection, invoice_id: str) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT amount, status, requested_by, approved_by FROM finance.credit_notes "
        "WHERE invoice_id = %s",
        (invoice_id,),
    ).fetchall()


@pytest.mark.usefixtures("clean_credit_notes")
async def test_s4_finance_drafts_a_credit_note_pending_approval(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    invoice_id = manifest["scenario_refs"]["S4_invoice"]
    ok, result = await as_user("finance1")(
        DRAFT, {"invoice_id": invoice_id, "amount": "500", "reason": "pytest: S4 damaged freight"}
    )
    assert ok, result
    assert result["status"] == "pending_approval"
    assert Decimal(result["amount"]) == Decimal("500")
    assert result["requested_by"] == manifest["users"]["finance1"]
    assert credit_notes_on(db, invoice_id) == [
        (Decimal("500.00"), "pending_approval", UUID(manifest["users"]["finance1"]), None)
    ]


@pytest.mark.usefixtures("clean_credit_notes")
async def test_rep_cannot_draft_a_credit_note_even_on_their_own_invoice(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    invoice_id = rep_invoice(db, manifest["users"]["rep1"])
    ok, message = await as_user("rep1")(
        DRAFT, {"invoice_id": invoice_id, "amount": "10", "reason": "pytest: rep attempt"}
    )
    assert not ok
    assert message == "forbidden: only finance can draft credit notes"
    assert credit_notes_on(db, invoice_id) == []


@pytest.mark.usefixtures("clean_credit_notes")
async def test_credit_can_never_exceed_the_invoice_amount(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    invoice_id = manifest["scenario_refs"]["S4_invoice"]  # 2450.00 in the seed
    total = db.execute(
        "SELECT amount FROM finance.invoices WHERE id = %s", (invoice_id,)
    ).fetchone()[0]
    call = as_user("finance1")

    ok, message = await call(
        DRAFT, {"invoice_id": invoice_id, "amount": str(total + 1), "reason": "pytest: too big"}
    )
    assert not ok and "exceeds" in message

    ok, _ = await call(
        DRAFT, {"invoice_id": invoice_id, "amount": str(total - 100), "reason": "pytest: part 1"}
    )
    assert ok
    ok, message = await call(
        DRAFT, {"invoice_id": invoice_id, "amount": "100.01", "reason": "pytest: part 2"}
    )
    assert not ok and "exceeds" in message
    ok, _ = await call(
        DRAFT, {"invoice_id": invoice_id, "amount": "100", "reason": "pytest: exactly the rest"}
    )
    assert ok
    assert sum(r[0] for r in credit_notes_on(db, invoice_id)) == total


@pytest.mark.usefixtures("clean_credit_notes")
async def test_concurrent_drafts_cannot_together_exceed_the_invoice(
    as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    """Two drafts of 60% each arrive together: the row lock lets exactly one through."""
    import anyio

    invoice_id = manifest["scenario_refs"]["S4_invoice"]
    total = db.execute(
        "SELECT amount FROM finance.invoices WHERE id = %s", (invoice_id,)
    ).fetchone()[0]
    share = str((total * Decimal("0.6")).quantize(Decimal("0.01")))
    call = as_user("finance1")
    outcomes: list[bool] = []

    async def draft(n: int) -> None:
        ok, _ = await call(
            DRAFT, {"invoice_id": invoice_id, "amount": share, "reason": f"pytest: race {n}"}
        )
        outcomes.append(ok)

    async with anyio.create_task_group() as tg:
        tg.start_soon(draft, 1)
        tg.start_soon(draft, 2)

    assert sorted(outcomes) == [False, True]
    assert sum(r[0] for r in credit_notes_on(db, invoice_id)) <= total


@pytest.mark.usefixtures("clean_credit_notes")
@pytest.mark.parametrize(
    ("amount", "reason"),
    [
        ("0", "pytest: zero"),
        ("-50", "pytest: negative"),
        ("10.001", "pytest: three decimals"),
        ("abc", "pytest: not a number"),
        ("10", "x"),  # reason too short
    ],
)
async def test_invalid_credit_note_input_is_rejected(
    amount: str, reason: str, as_user: Callable[[str], Call], db: psycopg.Connection
) -> None:
    ok, _ = await as_user("finance1")(
        DRAFT, {"invoice_id": "INV-1042", "amount": amount, "reason": reason}
    )
    assert not ok
    assert credit_notes_on(db, "INV-1042") == []


@pytest.mark.usefixtures("clean_credit_notes")
async def test_draft_on_a_missing_invoice_is_not_found(as_user: Callable[[str], Call]) -> None:
    ok, message = await as_user("finance1")(
        DRAFT, {"invoice_id": "INV-9999", "amount": "10", "reason": "pytest: missing"}
    )
    assert not ok
    assert message == "invoice INV-9999 not found"


# ------------------------------------------------------------------- leaks


@pytest.mark.parametrize("user", REPS)
async def test_no_forbidden_canary_in_anything_a_rep_can_reach(
    user: str, as_user: Callable[[str], Call], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    forbidden = [c["canary"] for c in manifest["canaries"] if user in c["forbidden_users"]]
    call = as_user(user)
    outputs: list[Any] = []
    for status in ("open", "paid", "overdue"):
        ok, listing = await call("list_invoices", {"status": status})
        assert ok, listing
        outputs.append(listing)
        for invoice in listing["invoices"][:10]:
            outputs.append((await call("get_invoice", {"invoice_id": invoice["id"]}))[1])
    text = json.dumps(outputs)
    assert [c for c in forbidden if c in text] == []
