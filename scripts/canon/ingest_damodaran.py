"""Ingest Aswath Damodaran's NYU Stern papers into the corpus.

Free + public academic distribution. PDF only. Reuses
``gecko_core.sources.pdf.extract`` and the standard chunker/embedder
stack. Chunks land with ``provider_kind="canon_damodaran"``.

Run:
    set -a; source .env; set +a
    uv run python scripts/canon/ingest_damodaran.py
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
from gecko_core.sources.canon_damodaran import paper_urls  # noqa: E402
from gecko_core.sources.pdf import extract as pdf_extract  # noqa: E402

log = logging.getLogger("canon.damodaran")

_CANON_DAMO_SESSION = uuid5(NAMESPACE_URL, "gecko.canon.damodaran.session.v1")


async def ingest_one(paper_url: str, slug: str, *, dry_run: bool) -> dict[str, int]:
    source_id = uuid5(NAMESPACE_URL, paper_url)
    try:
        text, fetch_seconds = await pdf_extract(paper_url)
    except Exception as exc:  # noqa: BLE001
        log.warning("FAIL %-30s fetch_error=%s", slug, exc)
        return {"chunks": 0, "fetched_bytes": 0, "skipped": 1}

    if not text:
        log.warning("EMPTY %-30s (extract returned blank — scanned PDF?)", slug)
        return {"chunks": 0, "fetched_bytes": 0, "skipped": 1}

    chunks_text = chunk(text)
    if not chunks_text:
        log.warning("EMPTY %-30s (chunker produced 0 chunks)", slug)
        return {"chunks": 0, "fetched_bytes": len(text), "skipped": 1}

    log.info(
        "FETCH %-30s bytes=%6d  chunks=%3d  fetch_s=%.2f",
        slug, len(text), len(chunks_text), fetch_seconds,
    )

    if dry_run:
        return {"chunks": len(chunks_text), "fetched_bytes": len(text), "skipped": 0}

    vectors, _tokens = await embed(chunks_text)
    rows: list[tuple[int, str, list[float]]] = [
        (i, chunks_text[i], list(vectors[i])) for i in range(len(chunks_text))
    ]
    inserted = await insert_chunks_mongo(
        session_id=_CANON_DAMO_SESSION,
        source_id=source_id,
        chunks=rows,
        category="investment_signals",
        vertical="dex",
        source="web",
        provider_kind="canon_damodaran",
        source_url=paper_url,
        freshness_tier="static",
        protocol=(),
        content_kind="mechanism",
    )
    log.info("INSERT %-30s new_chunks=%d", slug, inserted)
    return {"chunks": inserted, "fetched_bytes": len(text), "skipped": 0}


async def amain(*, dry_run: bool, limit: int | None, sleep_seconds: float) -> int:
    papers = paper_urls()
    if limit is not None:
        papers = papers[:limit]
    log.info("=== canon-damodaran ingest: %d papers (dry_run=%s) ===", len(papers), dry_run)

    total_chunks = 0
    total_skipped = 0
    total_bytes = 0
    for i, paper in enumerate(papers, start=1):
        log.info("[%d/%d] %s", i, len(papers), paper.slug)
        stats = await ingest_one(paper.url, paper.slug, dry_run=dry_run)
        total_chunks += stats["chunks"]
        total_skipped += stats["skipped"]
        total_bytes += stats["fetched_bytes"]
        if i < len(papers):
            await asyncio.sleep(sleep_seconds)

    log.info(
        "=== DONE: %d papers, %d chunks (written or planned), %d skipped, %d bytes ===",
        len(papers), total_chunks, total_skipped, total_bytes,
    )
    return 0


@click.command()
@click.option("--dry-run", is_flag=True, default=False, help="Fetch + chunk only; no Mongo writes.")
@click.option("--limit", type=int, default=None, help="Process at most this many papers.")
@click.option("--sleep-seconds", type=float, default=1.0, show_default=True,
              help="Politeness delay between fetches.")
@click.option("--verbose", "-v", is_flag=True, default=False)
def main(dry_run: bool, limit: int | None, sleep_seconds: float, verbose: bool) -> None:
    """Ingest Damodaran papers."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )
    rc = asyncio.run(amain(dry_run=dry_run, limit=limit, sleep_seconds=sleep_seconds))
    sys.exit(rc)


if __name__ == "__main__":
    main()
