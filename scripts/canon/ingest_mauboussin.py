"""Ingest Michael Mauboussin / Counterpoint Global PDFs into the corpus.

15 curated public-domain PDFs (see ``gecko_core.sources.canon_mauboussin``).
Chunks land with ``provider_kind="canon_mauboussin"``, ``protocol=()``
(cross-cutting canon, Pattern F), ``freshness_tier="static"``,
``content_kind="mechanism"``. Idempotent via (source_id, chunk_index).

    set -a; source .env; set +a   # MONGODB_URI + OPENAI_API_KEY
    uv run python scripts/canon/ingest_mauboussin.py --dry-run   # verify URLs
    uv run python scripts/canon/ingest_mauboussin.py             # live ingest
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import click

_REPO = Path(__file__).resolve().parents[2]
_GC_SRC = _REPO / "packages" / "gecko-core" / "src"
if str(_GC_SRC) not in sys.path:
    sys.path.insert(0, str(_GC_SRC))

from gecko_core.db.mongo_chunks import insert_chunks_mongo  # noqa: E402
from gecko_core.ingestion.chunker import chunk  # noqa: E402
from gecko_core.ingestion.embedder import embed  # noqa: E402
from gecko_core.sources.canon_mauboussin import (  # noqa: E402
    MAUBOUSSIN_SOURCES,
    CanonSource,
)
from gecko_core.sources.pdf import extract as pdf_extract  # noqa: E402

log = logging.getLogger("canon.mauboussin")

_SESSION = uuid5(NAMESPACE_URL, "gecko.canon.mauboussin.session.v1")
CHUNK_SIZE = 1000  # Mauboussin papers reward larger context windows
CHUNK_OVERLAP = 50


def _slug(s: CanonSource) -> str:
    words = s.title.replace(":", "").split()
    return f"{s.year}-" + "-".join(words[:4]).lower()


async def ingest_one(s: CanonSource, *, dry_run: bool) -> dict[str, int]:
    source_id = uuid5(NAMESPACE_URL, s.url)
    try:
        text, fetch_seconds = await pdf_extract(s.url)
    except Exception as exc:  # noqa: BLE001
        log.warning("FAIL | %s | %s", s.url, exc)
        return {"chunks": 0, "skipped": 1}
    if not text:
        log.warning("EMPTY | %s | blank extract (scanned PDF?)", s.url)
        return {"chunks": 0, "skipped": 1}
    chunks_text = chunk(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    if not chunks_text:
        log.warning("EMPTY | %s | chunker zero output", s.url)
        return {"chunks": 0, "skipped": 1}
    log.info("FETCH | %-48s bytes=%6d chunks=%3d fetch_s=%.2f",
             _slug(s), len(text), len(chunks_text), fetch_seconds)
    if dry_run:
        return {"chunks": len(chunks_text), "skipped": 0}
    vectors, _tokens = await embed(chunks_text)
    rows = [(i, chunks_text[i], list(vectors[i])) for i in range(len(chunks_text))]
    try:
        inserted = await insert_chunks_mongo(
            session_id=_SESSION, source_id=source_id, chunks=rows,
            category="investment_signals", vertical="dex", source="web",
            provider_kind="canon_mauboussin", source_url=s.url,
            freshness_tier="static", protocol=(), content_kind="mechanism",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("FAIL | %s | insert_error=%s", s.url, exc)
        return {"chunks": 0, "skipped": 1}
    log.info("OK    | %s | chunks=%d", s.url, inserted)
    return {"chunks": inserted, "skipped": 0}


async def amain(*, dry_run: bool, limit: int | None, sleep_seconds: float) -> int:
    sources = list(MAUBOUSSIN_SOURCES)[: limit] if limit else list(MAUBOUSSIN_SOURCES)
    log.info("=== canon-mauboussin: %d PDFs (dry_run=%s) ===", len(sources), dry_run)
    total_chunks = total_skipped = 0
    failures: list[str] = []
    for i, s in enumerate(sources, 1):
        log.info("[%d/%d] %s", i, len(sources), _slug(s))
        st = await ingest_one(s, dry_run=dry_run)
        total_chunks += st["chunks"]
        total_skipped += st["skipped"]
        if st["skipped"]:
            failures.append(s.url)
        if i < len(sources):
            await asyncio.sleep(sleep_seconds)
    log.info("=== DONE: chunks=%d skipped=%d ===", total_chunks, total_skipped)
    for url in failures:
        log.warning("  FAILED: %s", url)
    return 0


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Fetch+chunk only; no embed/Mongo.")
@click.option("--limit", type=int, default=None)
@click.option("--sleep-seconds", type=float, default=1.0, show_default=True)
@click.option("--verbose", "-v", is_flag=True, default=False)
def main(dry_run: bool, limit: int | None, sleep_seconds: float, verbose: bool) -> None:
    """Ingest Michael Mauboussin / Counterpoint Global papers."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-5s %(name)s %(message)s")
    sys.exit(asyncio.run(amain(dry_run=dry_run, limit=limit, sleep_seconds=sleep_seconds)))


if __name__ == "__main__":
    main()
