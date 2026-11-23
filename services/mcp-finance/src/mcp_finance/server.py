"""Northstar Finance MCP server.

Reps see invoices for their own accounts, finance sees all, contractors are forbidden.
Only finance may draft a credit note, and a draft is never issued here: approval comes from
the gateway (phase 6). bank_ref is returned as stored; the gateway redacts it before the LLM.
"""

from dataclasses import asdict
from decimal import Decimal

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_finance.auth import current_user
from mcp_finance.models import (
    AccountId,
    Amount,
    CreditNote,
    Invoice,
    InvoiceId,
    InvoiceList,
    InvoiceStatus,
    InvoiceSummary,
    Reason,
)
from mcp_finance.settings import get_settings
from northstar_common.access import VISIBLE_ACCOUNT, account_scope
from northstar_common.db import make_lifespan, read_only, read_write
from northstar_common.errors import Forbidden, NotFound
from northstar_common.serve import serve

LIST_LIMIT = 100

mcp = MCPServer("northstar-finance", lifespan=make_lifespan(get_settings, "mcp-finance"))


ACCOUNT_VISIBLE_SQL = f"""
    SELECT 1 FROM crm.accounts a WHERE a.id = %(account_id)s AND {VISIBLE_ACCOUNT}
"""  # noqa: S608 - only constant SQL is interpolated; all values are bound parameters

LIST_INVOICES_SQL = f"""
    SELECT i.id, i.account_id, i.amount, i.due_date, i.status
    FROM finance.invoices i
    JOIN crm.accounts a ON a.id = i.account_id
    WHERE {VISIBLE_ACCOUNT}
      AND (%(account_id)s::text IS NULL OR i.account_id = %(account_id)s)
      AND (%(status)s::text IS NULL OR i.status = %(status)s)
    ORDER BY i.id
    LIMIT %(limit)s
"""  # noqa: S608 - only constant SQL is interpolated; all values are bound parameters


@mcp.tool()
async def list_invoices(
    ctx: Context, account_id: AccountId | None = None, status: InvoiceStatus | None = None
) -> InvoiceList:
    """List invoices the signed-in user is allowed to see, optionally for one account or status.

    Returns at most 100 invoices; `truncated` is true if there were more (narrow the filter).
    """
    scope = account_scope(current_user(ctx))
    params = {
        **asdict(scope),
        "account_id": account_id,
        "status": status,
        "limit": LIST_LIMIT + 1,  # one extra row tells us whether we truncated
    }
    async with read_only(ctx) as cur:
        if account_id is not None:
            await cur.execute(ACCOUNT_VISIBLE_SQL, params)
            if await cur.fetchone() is None:
                raise NotFound("account", account_id)
        await cur.execute(LIST_INVOICES_SQL, params)
        rows = await cur.fetchall()
    return InvoiceList(
        invoices=[InvoiceSummary(**r) for r in rows[:LIST_LIMIT]],
        truncated=len(rows) > LIST_LIMIT,
    )


GET_INVOICE_SQL = f"""
    SELECT i.id, i.account_id, a.name AS account_name, i.amount, i.due_date, i.status, i.bank_ref
    FROM finance.invoices i
    JOIN crm.accounts a ON a.id = i.account_id
    WHERE i.id = %(invoice_id)s AND {VISIBLE_ACCOUNT}
"""  # noqa: S608 - only constant SQL is interpolated; all values are bound parameters


@mcp.tool()
async def get_invoice(ctx: Context, invoice_id: InvoiceId) -> Invoice:
    """Get one invoice the signed-in user is allowed to see, including payment details."""
    scope = account_scope(current_user(ctx))
    async with read_only(ctx) as cur:
        await cur.execute(GET_INVOICE_SQL, {**asdict(scope), "invoice_id": invoice_id})
        row = await cur.fetchone()
    if row is None:
        raise NotFound("invoice", invoice_id)
    return Invoice(**row)


LOCK_INVOICE_SQL = "SELECT amount FROM finance.invoices WHERE id = %(invoice_id)s FOR UPDATE"
CREDITED_SQL = """
    SELECT COALESCE(SUM(amount), 0) AS credited
    FROM finance.credit_notes
    WHERE invoice_id = %(invoice_id)s AND status <> 'rejected'
"""
INSERT_CREDIT_NOTE_SQL = """
    INSERT INTO finance.credit_notes (invoice_id, amount, reason, requested_by)
    VALUES (%(invoice_id)s, %(amount)s, %(reason)s, %(requested_by)s)
    RETURNING id, invoice_id, amount, reason, status, requested_by, created_at
"""


@mcp.tool()
async def draft_credit_note(
    ctx: Context, invoice_id: InvoiceId, amount: Amount, reason: Reason
) -> CreditNote:
    """Draft a credit note against an invoice (finance only).

    The draft is created as pending approval; nothing is issued until it is approved.
    The total of non-rejected credit notes on an invoice can't exceed the invoice amount.
    """
    identity = current_user(ctx)
    if identity.role != "finance_analyst":
        raise Forbidden("only finance can draft credit notes")

    params = {
        "invoice_id": invoice_id,
        "amount": amount,
        "reason": reason.strip(),
        "requested_by": identity.user_id,
    }
    async with read_write(ctx) as cur:
        # Lock the invoice row so two concurrent drafts can't both pass the limit check.
        await cur.execute(LOCK_INVOICE_SQL, params)
        invoice = await cur.fetchone()
        if invoice is None:
            raise NotFound("invoice", invoice_id)
        await cur.execute(CREDITED_SQL, params)
        credited: Decimal = (await cur.fetchone())["credited"]
        remaining = invoice["amount"] - credited
        if amount > remaining:
            raise ToolError(
                f"amount {amount} exceeds the remaining creditable amount "
                f"{remaining} on {invoice_id}"
            )
        await cur.execute(INSERT_CREDIT_NOTE_SQL, params)
        row = await cur.fetchone()
    return CreditNote(**row)


def main() -> None:
    serve(mcp, get_settings())


if __name__ == "__main__":
    main()
