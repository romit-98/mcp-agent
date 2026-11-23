"""Northstar Email MCP server (mock).

Who may email whom (spec section 3):
  - sales rep: internal staff, and contacts on accounts they own
  - finance:   internal staff only
  - contractor: nobody
Addresses are compared case-insensitively. Every refusal says the same thing, so the reply
can't be used to find out whose contact an address is.

This decides whether a recipient is *allowed*. Whether it came from the user or from untrusted
text (argument provenance) is the gateway's job in phase 6.
"""

from mcp.server.mcpserver import Context, MCPServer

from mcp_email.auth import current_user
from mcp_email.models import Body, EmailAddress, SentEmail, Subject
from mcp_email.settings import get_settings
from northstar_common.db import make_lifespan, read_write
from northstar_common.errors import Forbidden
from northstar_common.serve import serve

mcp = MCPServer("northstar-email", lifespan=make_lifespan(get_settings, "mcp-email"))

RECIPIENT_NOT_ALLOWED = "recipient not allowed"

INTERNAL_STAFF_SQL = """
    SELECT 1 FROM iam.users
    WHERE lower(email) = %(to)s AND split_part(lower(email), '@', 2) = %(internal_domain)s
"""
OWN_CONTACT_SQL = """
    SELECT 1 FROM crm.contacts c
    JOIN crm.accounts a ON a.id = c.account_id
    WHERE lower(c.email) = %(to)s AND a.owner_user_id = %(user_id)s
"""
INSERT_OUTBOX_SQL = """
    INSERT INTO email.outbox (sender_user_id, to_address, subject, body)
    VALUES (%(user_id)s, %(to)s, %(subject)s, %(body)s)
    RETURNING id, to_address AS to, subject, created_at
"""


@mcp.tool()
async def send_email(ctx: Context, to: EmailAddress, subject: Subject, body: Body) -> SentEmail:
    """Send an email as the signed-in user (mock: it is written to an outbox, not sent).

    Sales reps may email internal staff and contacts on their own accounts; finance may email
    internal staff only. Any other recipient is refused.
    """
    identity = current_user(ctx)
    if identity.role not in ("sales_rep", "finance_analyst"):
        raise Forbidden()

    params = {
        "to": to.strip().lower(),
        "subject": subject,
        "body": body,
        "user_id": identity.user_id,
        "internal_domain": get_settings().internal_domain.lower(),
    }
    async with read_write(ctx) as cur:
        await cur.execute(INTERNAL_STAFF_SQL, params)
        allowed = await cur.fetchone() is not None
        if not allowed and identity.role == "sales_rep":
            await cur.execute(OWN_CONTACT_SQL, params)
            allowed = await cur.fetchone() is not None
        if not allowed:
            raise Forbidden(RECIPIENT_NOT_ALLOWED)
        await cur.execute(INSERT_OUTBOX_SQL, params)
        row = await cur.fetchone()
    return SentEmail(**row)


def main() -> None:
    serve(mcp, get_settings())


if __name__ == "__main__":
    main()
