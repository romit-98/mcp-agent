"""Tool inputs and outputs. Document text is untrusted content (security rule 5)."""

from typing import Annotated

from pydantic import BaseModel, Field

from northstar_common.untrusted import UntrustedText

Query = Annotated[str, Field(min_length=2, max_length=500, description="What to look for")]
TopK = Annotated[int, Field(ge=1, le=20, description="How many chunks to return (1-20)")]


class DocChunk(BaseModel):
    document_id: str
    title: str
    chunk_id: int
    score: float = Field(description="Reciprocal rank fusion score; higher is more relevant")
    content: UntrustedText


class SearchResult(BaseModel):
    query: str
    results: list[DocChunk]
