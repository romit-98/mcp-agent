"""search_docs against the seeded, ingested database, as each role (security rule 6).

Ground truth for "allowed" comes from knowledge.document_access, never from the code under test.
"""

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from mcp import Client

from mcp_knowledge import server
from mcp_knowledge.auth import Identity, Role
from mcp_knowledge.ingest import chunk_text

pytestmark = pytest.mark.anyio

ROLES: dict[str, Role] = {
    "rep1": "sales_rep",
    "finance1": "finance_analyst",
    "contractor1": "contractor",
}

Search = Callable[..., Awaitable[tuple[bool, Any]]]


async def _search(query: str, k: int = 5) -> tuple[bool, Any]:
    async with Client(server.mcp) as client:
        result = await client.call_tool("search_docs", {"query": query, "k": k})
    if result.is_error:
        text = " ".join(getattr(block, "text", "") for block in result.content)
        return False, re.sub(r"^Error executing tool \w+: ", "", text)
    return True, result.structured_content


@pytest.fixture
def as_user(
    monkeypatch: pytest.MonkeyPatch, manifest: dict[str, Any], ingested: psycopg.Connection
) -> Callable[[str], Search]:
    def use(username: str) -> Search:
        identity = Identity(user_id=UUID(manifest["users"][username]), role=ROLES[username])
        monkeypatch.setattr(server, "current_user", lambda _ctx: identity)
        return _search

    return use


def allowed_docs(db: psycopg.Connection, role: str) -> set[str]:
    rows = db.execute(
        "SELECT document_id FROM knowledge.document_access WHERE role = %s", (role,)
    ).fetchall()
    return {r[0] for r in rows}


def doc_ids(result: dict[str, Any]) -> list[str]:
    return [r["document_id"] for r in result["results"]]


# ------------------------------------------------------------- S3: refund policy


async def test_s3_contractor_gets_the_partner_refund_policy_never_the_finance_one(
    as_user: Callable[[str], Search], manifest: dict[str, Any]
) -> None:
    refs = manifest["scenario_refs"]
    ok, result = await as_user("contractor1")("What's our refund policy?")
    assert ok, result
    assert doc_ids(result)[0] == refs["S3_contractor_refund_doc"]
    assert refs["S3_finance_refund_doc"] not in doc_ids(result)


async def test_finance_gets_the_finance_refund_policy(
    as_user: Callable[[str], Search], manifest: dict[str, Any]
) -> None:
    ok, result = await as_user("finance1")("refund and credit note approval limits")
    assert ok, result
    assert doc_ids(result)[0] == manifest["scenario_refs"]["S3_finance_refund_doc"]


# ----------------------------------------------------------------- no leaks


@pytest.mark.parametrize("user", list(ROLES))
async def test_searching_every_title_only_ever_returns_allowed_documents(
    user: str,
    as_user: Callable[[str], Search],
    manifest: dict[str, Any],
    ingested: psycopg.Connection,
) -> None:
    """Every role searches the exact title of all 60 documents, including ones it can't read."""
    allowed = allowed_docs(ingested, ROLES[user])
    forbidden_canaries = [c["canary"] for c in manifest["canaries"] if user in c["forbidden_users"]]
    search = as_user(user)
    outputs = []
    for (title,) in ingested.execute("SELECT title FROM knowledge.documents ORDER BY id"):
        ok, result = await search(title, k=10)
        assert ok, result
        assert set(doc_ids(result)) <= allowed, f"{user} got a forbidden doc for {title!r}"
        outputs.append(result)
    text = json.dumps(outputs)
    assert [c for c in forbidden_canaries if c in text] == []


@pytest.mark.parametrize("user", list(ROLES))
async def test_hr_confidential_documents_are_never_returned(
    user: str, as_user: Callable[[str], Search], ingested: psycopg.Connection
) -> None:
    hr_docs = {
        r[0]
        for r in ingested.execute(
            "SELECT id FROM knowledge.documents WHERE classification = 'hr_confidential'"
        )
    }
    search = as_user(user)
    for query in ("salary bands pay review", "redundancy planning", "disciplinary case"):
        ok, result = await search(query, k=20)
        assert ok, result
        assert not set(doc_ids(result)) & hr_docs


async def test_no_identity_is_unauthenticated(ingested: psycopg.Connection) -> None:
    ok, message = await _search("refund policy")
    assert not ok
    assert message == "unauthenticated"


# ------------------------------------------------------------ retrieval quality


async def test_every_readable_document_is_found_by_its_title(
    as_user: Callable[[str], Search], ingested: psycopg.Connection
) -> None:
    """Retrieval sanity: finance can read 55 documents; each title should find its document."""
    search = as_user("finance1")
    misses = []
    rows = ingested.execute(
        "SELECT d.id, d.title FROM knowledge.documents d "
        "JOIN knowledge.document_access da ON da.document_id = d.id "
        "WHERE da.role = 'finance_analyst' ORDER BY d.id"
    ).fetchall()
    for doc_id, title in rows:
        ok, result = await search(title, k=3)
        assert ok, result
        if doc_id not in doc_ids(result):
            misses.append(title)
    assert misses == []


async def test_keyword_search_finds_exact_terms(as_user: Callable[[str], Search]) -> None:
    ok, result = await as_user("finance1")("BAS lodgement")
    assert ok, result
    assert result["results"][0]["title"] == "GST and BAS lodgement guide"


async def test_meaning_search_finds_paraphrases(
    as_user: Callable[[str], Search], manifest: dict[str, Any]
) -> None:
    ok, result = await as_user("contractor1")("customer wants money back for broken goods")
    assert ok, result
    assert manifest["scenario_refs"]["S3_contractor_refund_doc"] in doc_ids(result)[:3]


# ------------------------------------------------------------------- shape


async def test_results_are_marked_untrusted_with_their_source(
    as_user: Callable[[str], Search],
) -> None:
    ok, result = await as_user("rep1")("fatigue management", k=3)
    assert ok, result
    for r in result["results"]:
        assert r["content"]["trust"] == "untrusted"
        assert r["content"]["source"] == f"knowledge.documents:{r['document_id']}"


@pytest.mark.parametrize("k", [1, 7, 20])
async def test_k_limits_the_number_of_results(k: int, as_user: Callable[[str], Search]) -> None:
    ok, result = await as_user("finance1")("policy procedure guide", k=k)
    assert ok, result
    assert len(result["results"]) == k


@pytest.mark.parametrize(("query", "k"), [("refund", 0), ("refund", 21), ("x", 5), ("", 5)])
async def test_invalid_input_is_rejected(
    query: str, k: int, as_user: Callable[[str], Search]
) -> None:
    ok, _ = await as_user("rep1")(query, k=k)
    assert not ok


async def test_sql_looking_queries_are_just_text(as_user: Callable[[str], Search]) -> None:
    ok, result = await as_user("contractor1")("refund' OR 1=1; DROP TABLE knowledge.chunks; --")
    assert ok, result  # bound parameters: no error, just a (harmless) search


# ------------------------------------------------------------------ chunking


def test_chunking_keeps_paragraphs_whole_and_bounded() -> None:
    body = "\n\n".join(["a" * 300, "b" * 300, "c" * 300, "d" * 1000])
    chunks = chunk_text(body, max_chars=800)
    assert chunks == ["a" * 300 + "\n\n" + "b" * 300, "c" * 300, "d" * 1000]
