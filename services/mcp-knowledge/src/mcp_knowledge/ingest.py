"""Chunk and embed every document into knowledge.chunks. Safe to re-run.

    uv run --env-file ../../.env python -m mcp_knowledge.ingest

Run it after (re)seeding: the seed empties knowledge.chunks. The full-text column (tsv) is a
generated column, so Postgres keeps it in step with `content` by itself.
"""

import psycopg

from mcp_knowledge.embeddings import get_embedder, to_pgvector
from mcp_knowledge.settings import get_settings

MAX_CHUNK_CHARS = 800


def chunk_text(body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraphs, packing whole paragraphs into chunks of at most max_chars.

    A paragraph longer than max_chars becomes its own chunk rather than being cut mid-sentence.
    """
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def main() -> None:
    s = get_settings()
    embedder = get_embedder()
    with psycopg.connect(
        host=s.db_host,
        port=s.db_port,
        dbname=s.db_name,
        user=s.db_user,
        password=s.db_password.get_secret_value(),
        application_name="knowledge-ingest",
    ) as conn:
        documents = conn.execute(
            "SELECT id, title, body FROM knowledge.documents ORDER BY id"
        ).fetchall()

        rows: list[tuple[str, int, str]] = []
        for doc_id, _title, body in documents:
            rows += [(doc_id, i, chunk) for i, chunk in enumerate(chunk_text(body))]
        titles = {doc_id: title for doc_id, title, _ in documents}
        # The title gives each chunk its topic, which short chunks otherwise lack.
        vectors = embedder.embed_passages([f"{titles[d]}\n\n{c}" for d, _, c in rows])

        with conn.transaction():
            conn.execute("DELETE FROM knowledge.chunks")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO knowledge.chunks (document_id, chunk_index, content, embedding) "
                    "VALUES (%s, %s, %s, %s::vector)",
                    [(d, i, c, to_pgvector(v)) for (d, i, c), v in zip(rows, vectors, strict=True)],
                )
    print(f"ingested {len(documents)} documents into {len(rows)} chunks ({embedder.dim} dims)")


if __name__ == "__main__":
    main()
