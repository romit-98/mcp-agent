"""Tool inputs and outputs.

The recipient is one plain address: no display names, no lists, no line breaks. Line breaks in
`to` or `subject` are how header injection works ("...\\nBcc: attacker@..."), so both reject them.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

EmailAddress = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$",
        max_length=254,
        description="One recipient address, e.g. jane.doe@example.com",
    ),
]
Subject = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^\r\n]*$")]
Body = Annotated[str, Field(min_length=1, max_length=10_000)]


class SentEmail(BaseModel):
    id: int
    to: str
    subject: str
    created_at: datetime
    message: str = "Queued in the mock outbox. Nothing is really sent."
