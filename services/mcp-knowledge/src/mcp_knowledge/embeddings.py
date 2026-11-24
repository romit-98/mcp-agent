"""The one embedding interface (stack rule: providers are swappable).

Default: BAAI/bge-small-en-v1.5 via fastembed (ONNX, CPU, local). Free, nothing leaves the
machine, and the same text always gives the same vector, which keeps evals reproducible.
Phase 8 can add an Azure OpenAI implementation of the same protocol.
"""

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from mcp_knowledge.settings import get_settings


class Embedder(Protocol):
    dim: int

    def embed_query(self, text: str) -> list[float]: ...

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedder:
    """bge models expect queries and passages to be embedded slightly differently."""

    def __init__(self, model_name: str, dim: int, cache_dir: str | None = None) -> None:
        from fastembed import TextEmbedding  # heavy import, only when actually used

        self.dim = dim
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)

    def embed_query(self, text: str) -> list[float]:
        return self._check(next(iter(self._model.query_embed(text))).tolist())

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._check(v.tolist()) for v in self._model.passage_embed(list(texts))]

    def _check(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dim:
            raise ValueError(f"embedding has {len(vector)} dims, schema expects {self.dim}")
        return vector


@lru_cache
def get_embedder() -> Embedder:
    """Load the model once per process (about 67 MB; downloaded on first use if not cached)."""
    s = get_settings()
    return FastEmbedder(s.embedding_model, s.embedding_dim, s.model_cache_dir)


def to_pgvector(vector: Sequence[float]) -> str:
    """pgvector's text form, e.g. '[0.1,0.2]'. Bound as a parameter and cast with ::vector."""
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
