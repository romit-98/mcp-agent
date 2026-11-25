"""INSECURE BASELINE MCP server: the "before" in the before/after comparison.

Deliberate weaknesses, each one a common real-world mistake (and each one a scenario):
  - identity is a plain-text `acting_user` argument the LLM fills in       (role claims)
  - one all-access database account; no row-level security                (all scenarios)
  - list tools filter by owner, but fetch-by-ID tools don't check (IDOR)  (S2)
  - account notes and documents returned as plain text, not marked        (S5)
  - bank_ref returned to the model unredacted                             (leakage)
  - credit notes are issued immediately, no human approval                (S4)
  - any email recipient is accepted                                       (S5, S6)
  - document search has no access filter, HR documents included           (S3)
The only "permission check" is the system prompt asking the model to behave.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_insecure.settings import get_settings
from mcp_knowledge.embeddings import FastEmbedder, to_pgvector
from northstar_common.db import make_lifespan, read_only, read_write
from northstar_common.serve import serve

mcp = MCPServer("northstar-insecure-baseline", lifespan=make_lifespan(get_settings, "mcp-insecure"))


@lru_cache
def embedder() -> FastEmbedder:
    return FastEmbedder("BAAI/bge-small-en-v1.5", 384, get_settings().model_cache_dir)


async def user_row(ctx: Context, username: str) -> dict[str, Any]:
    async with read_only(ctx) as cur:
        await cur.execute("SELECT id, username FROM iam.users WHERE username = %s", (username,))
        row = await cur.fetchone()
    if row is None:
        raise ToolError(f"unknown user {username}")
    return row


def is_finance(username: str) -> bool:
    return username.startswith("finance")  # naive role from the username


# ------------------------------------------------------------------------- CRM


@mcp.tool()
async def search_accounts(
    ctx: Context, acting_user: str, query: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    """Search customer accounts. Pass the current user's username as acting_user."""
    sql = (
        "SELECT a.id, a.name, a.region, a.status FROM crm.accounts a "
        "JOIN iam.users u ON u.id = a.owner_user_id WHERE TRUE"
    )
    params: list[Any] = []
    if not is_finance(acting_user):
        sql += " AND u.username = %s"
        params.append(acting_user)
    if query:
        sql += " AND a.name ILIKE %s"
        params.append(f"%{query}%")
    if status:
        sql += " AND a.status = %s"
        params.append(status)
    async with read_only(ctx) as cur:
        await cur.execute(sql + " ORDER BY a.id", params)
        return await cur.fetchall()


@mcp.tool()
async def get_account(ctx: Context, acting_user: str, account_id: str) -> dict[str, Any]:
    """Get one customer account, including its notes. Pass the current user as acting_user."""
    async with read_only(ctx) as cur:
        await cur.execute(
            "SELECT a.id, a.name, a.region, a.status, u.username AS owner, a.notes "
            "FROM crm.accounts a JOIN iam.users u ON u.id = a.owner_user_id WHERE a.id = %s",
            (account_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise ToolError(f"account {account_id} not found")
    return row


@mcp.tool()
async def list_contacts(ctx: Context, acting_user: str, account_id: str) -> list[dict[str, Any]]:
    """List an account's contacts. Pass the current user as acting_user."""
    async with read_only(ctx) as cur:
        await cur.execute(
            "SELECT id, name, email, phone, is_billing FROM crm.contacts "
            "WHERE account_id = %s ORDER BY is_billing DESC, id",
            (account_id,),
        )
        return await cur.fetchall()


# --------------------------------------------------------------------- Finance


@mcp.tool()
async def list_invoices(
    ctx: Context, acting_user: str, account_id: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    """List invoices, optionally for one account or status. Pass the current user as acting_user."""
    sql = (
        "SELECT i.id, i.account_id, i.amount, i.due_date, i.status FROM finance.invoices i "
        "JOIN crm.accounts a ON a.id = i.account_id JOIN iam.users u ON u.id = a.owner_user_id "
        "WHERE TRUE"
    )
    params: list[Any] = []
    if account_id:
        sql += " AND i.account_id = %s"  # trusts the caller to only ask for their own account
        params.append(account_id)
    elif not is_finance(acting_user):
        sql += " AND u.username = %s"
        params.append(acting_user)
    if status:
        sql += " AND i.status = %s"
        params.append(status)
    async with read_only(ctx) as cur:
        await cur.execute(sql + " ORDER BY i.id LIMIT 100", params)
        return await cur.fetchall()


@mcp.tool()
async def get_invoice(ctx: Context, acting_user: str, invoice_id: str) -> dict[str, Any]:
    """Get one invoice with payment details. Pass the current user as acting_user."""
    async with read_only(ctx) as cur:
        await cur.execute(
            "SELECT i.id, i.account_id, a.name AS account_name, i.amount, i.due_date, i.status, "
            "i.bank_ref FROM finance.invoices i JOIN crm.accounts a ON a.id = i.account_id "
            "WHERE i.id = %s",
            (invoice_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise ToolError(f"invoice {invoice_id} not found")
    return row


@mcp.tool()
async def draft_credit_note(
    ctx: Context, acting_user: str, invoice_id: str, amount: Decimal, reason: str
) -> dict[str, Any]:
    """Create a credit note against an invoice. Pass the current user as acting_user."""
    user = await user_row(ctx, acting_user)
    async with read_write(ctx) as cur:
        await cur.execute(
            "INSERT INTO finance.credit_notes "
            "(invoice_id, amount, reason, status, requested_by, approved_by) "
            "VALUES (%s, %s, %s, 'approved', %s, %s) "
            "RETURNING id, invoice_id, amount, reason, status",
            (invoice_id, amount, reason, user["id"], user["id"]),
        )
        return await cur.fetchone()


# ----------------------------------------------------------------------- Email


@mcp.tool()
async def send_email(
    ctx: Context, acting_user: str, to: str, subject: str, body: str
) -> dict[str, Any]:
    """Send an email on behalf of the current user (acting_user)."""
    user = await user_row(ctx, acting_user)
    async with read_write(ctx) as cur:
        await cur.execute(
            "INSERT INTO email.outbox (sender_user_id, to_address, subject, body) "
            "VALUES (%s, %s, %s, %s) RETURNING id, to_address, subject",
            (user["id"], to, subject, body),
        )
        return await cur.fetchone()


# ------------------------------------------------------------------- Knowledge

SEARCH_SQL = """
    WITH vec AS (
        SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector, c.id) AS rank
        FROM knowledge.chunks c ORDER BY c.embedding <=> %(qvec)s::vector, c.id LIMIT 50
    ),
    fts AS (
        SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q) DESC, c.id) AS rank
        FROM knowledge.chunks c, websearch_to_tsquery('english', %(query)s) AS q
        WHERE c.tsv @@ q ORDER BY ts_rank_cd(c.tsv, q) DESC, c.id LIMIT 50
    ),
    fused AS (
        SELECT id, SUM(1.0 / (60 + rank)) AS score
        FROM (SELECT id, rank FROM vec UNION ALL SELECT id, rank FROM fts) r GROUP BY id
    )
    SELECT d.id AS document_id, d.title, c.content
    FROM fused f JOIN knowledge.chunks c ON c.id = f.id
    JOIN knowledge.documents d ON d.id = c.document_id
    ORDER BY f.score DESC, c.id LIMIT %(k)s
"""


@mcp.tool()
async def search_docs(
    ctx: Context, acting_user: str, query: str, k: int = 5
) -> list[dict[str, Any]]:
    """Search company documents. Pass the current user as acting_user."""
    qvec = await anyio.to_thread.run_sync(embedder().embed_query, query)
    async with read_only(ctx) as cur:
        await cur.execute(SEARCH_SQL, {"qvec": to_pgvector(qvec), "query": query, "k": k})
        return await cur.fetchall()


def main() -> None:
    embedder()
    serve(mcp, get_settings())


if __name__ == "__main__":
    main()
