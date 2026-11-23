"""Deliberate tool failures.

All are ToolErrors, so the caller sees exactly this message as an error result. Anything else
that escapes a tool is treated by the SDK as a crash and shown only as "Error executing tool".
"""

from mcp.server.mcpserver.exceptions import ToolError


class Unauthenticated(ToolError):
    """No trustworthy identity on the request. Deliberately says nothing about why."""

    def __init__(self) -> None:
        super().__init__("unauthenticated")


class Forbidden(ToolError):
    """The caller's role may not use this tool, or may not do this particular thing."""

    def __init__(self, reason: str | None = None) -> None:
        super().__init__(f"forbidden: {reason}" if reason else "forbidden")


class NotFound(ToolError):
    """Missing and not-yours look identical, so the reply can't confirm a record exists."""

    def __init__(self, kind: str, record_id: str) -> None:
        super().__init__(f"{kind} {record_id} not found")
