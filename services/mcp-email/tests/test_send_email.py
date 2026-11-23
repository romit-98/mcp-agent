"""send_email against the seeded database, as each role.

Identity is patched in (current_user is tested in libs/northstar-common). Every allowed send
must land in the outbox; every refused one must leave it untouched.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from mcp import Client

from mcp_email import server
from mcp_email.auth import Identity, Role

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("clean_outbox")]

ROLES: dict[str, Role] = {
    "rep1": "sales_rep",
    "rep2": "sales_rep",
    "rep3": "sales_rep",
    "finance1": "finance_analyst",
    "contractor1": "contractor",
}
NOT_ALLOWED = "forbidden: recipient not allowed"

Send = Callable[..., Awaitable[tuple[bool, Any]]]


async def _send(to: str, subject: str = "pytest: hello", body: str = "Hi") -> tuple[bool, Any]:
    async with Client(server.mcp) as client:
        result = await client.call_tool("send_email", {"to": to, "subject": subject, "body": body})
    if result.is_error:
        text = " ".join(getattr(block, "text", "") for block in result.content)
        return False, re.sub(r"^Error executing tool \w+: ", "", text)
    return True, result.structured_content


@pytest.fixture
def as_user(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any], db: psycopg.Connection
) -> Callable[[str], Send]:
    def use(username: str) -> Send:
        identity = Identity(user_id=UUID(manifest["users"][username]), role=ROLES[username])
        monkeypatch.setattr(server, "current_user", lambda _ctx: identity)
        return _send

    return use


def outbox(db: psycopg.Connection) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT sender_user_id, to_address FROM email.outbox WHERE subject LIKE 'pytest:%' "
        "ORDER BY id"
    ).fetchall()


def contact_of(db: psycopg.Connection, owner_id: str) -> str:
    """Billing contact on the first account the user owns."""
    return db.execute(
        "SELECT c.email FROM crm.contacts c JOIN crm.accounts a ON a.id = c.account_id "
        "WHERE a.owner_user_id = %s AND c.is_billing ORDER BY a.id LIMIT 1",
        (owner_id,),
    ).fetchone()[0]


# ------------------------------------------------------------------- allowed


async def test_s6_rep_emails_their_accounts_billing_contact(
    as_user: Callable[[str], Send], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    to = manifest["scenario_refs"]["S6_billing_email"]
    ok, result = await as_user("rep1")(to, "pytest: INV-1007", "Please find INV-1007 attached.")
    assert ok, result
    assert result["to"] == to
    assert outbox(db) == [(UUID(manifest["users"]["rep1"]), to)]


async def test_recipient_match_ignores_case_and_is_stored_lowercase(
    as_user: Callable[[str], Send], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    to = manifest["scenario_refs"]["S6_billing_email"]
    ok, result = await as_user("rep1")(to.upper())
    assert ok, result
    assert outbox(db) == [(UUID(manifest["users"]["rep1"]), to)]


@pytest.mark.parametrize("sender", ["rep1", "finance1"])
async def test_staff_can_email_internal_staff(
    sender: str, as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, result = await as_user(sender)("rep3@northstar.example")
    assert ok, result
    assert len(outbox(db)) == 1


# ------------------------------------------------------------------- refused


async def test_s6_rep_cannot_email_an_outside_address(
    as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, message = await as_user("rep1")("someone@gmail.com")
    assert not ok
    assert message == NOT_ALLOWED
    assert outbox(db) == []


async def test_s5_injected_exfiltration_address_is_refused(
    as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, message = await as_user("rep1")("exfil@evil.example")
    assert not ok
    assert message == NOT_ALLOWED
    assert outbox(db) == []


async def test_rep_cannot_email_another_reps_contact_and_cannot_tell_why(
    as_user: Callable[[str], Send], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    rep2_contact = contact_of(db, manifest["users"]["rep2"])
    send = as_user("rep1")
    refusals = [
        await send(rep2_contact),  # a real contact, but not rep1's
        await send("nobody@nowhere.example"),  # doesn't exist anywhere
    ]
    assert refusals == [(False, NOT_ALLOWED), (False, NOT_ALLOWED)]
    assert outbox(db) == []


async def test_finance_cannot_email_customer_contacts(
    as_user: Callable[[str], Send], manifest: dict[str, Any], db: psycopg.Connection
) -> None:
    ok, message = await as_user("finance1")(manifest["scenario_refs"]["S6_billing_email"])
    assert not ok
    assert message == NOT_ALLOWED
    assert outbox(db) == []


@pytest.mark.parametrize(
    "to",
    [
        "contractor1@contractor.example",  # a Northstar user, but not internal staff
        "ceo@northstar.example",  # internal domain, but not a real staff member
        "rep3@northstar.example.evil.example",  # lookalike domain
    ],
)
async def test_only_real_internal_staff_count_as_internal(
    to: str, as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, message = await as_user("finance1")(to)
    assert not ok
    assert message == NOT_ALLOWED
    assert outbox(db) == []


async def test_contractor_cannot_send_email(
    as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, message = await as_user("contractor1")("rep1@northstar.example")
    assert not ok
    assert message == "forbidden"
    assert outbox(db) == []


async def test_no_identity_is_unauthenticated(db: psycopg.Connection) -> None:
    ok, message = await _send("rep1@northstar.example")
    assert not ok
    assert message == "unauthenticated"
    assert outbox(db) == []


# ---------------------------------------------------------------- input shape


@pytest.mark.parametrize(
    "to",
    [
        "rep3@northstar.example, exfil@evil.example",  # a list
        "Rep Three <rep3@northstar.example>",  # display name
        "rep3@northstar.example\nBcc: exfil@evil.example",  # header injection
        "rep3@northstar.example\r\n",
        "rep3",
        "",
    ],
)
async def test_recipient_must_be_one_plain_address(
    to: str, as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, message = await as_user("rep1")(to)
    assert not ok
    assert "pattern" in message.lower() or "at least" in message.lower()
    assert outbox(db) == []


@pytest.mark.parametrize(
    "subject", ["pytest: hi\nBcc: exfil@evil.example", "pytest: hi\r\nX-Evil: 1", ""]
)
async def test_subject_cannot_carry_extra_headers(
    subject: str, as_user: Callable[[str], Send], db: psycopg.Connection
) -> None:
    ok, _ = await as_user("rep1")("rep3@northstar.example", subject)
    assert not ok
    assert outbox(db) == []
