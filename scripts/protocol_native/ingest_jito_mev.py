"""S31-#50 — ingest Jito MEV-tip-floor / bundle-mechanics content.

Mirrors the shape of the broader ``ingest_protocol_native.py`` pattern
(see sibling worktree for the full multi-protocol catalog). Differs
in scope:

  - Only Jito MEV-side endpoints. JitoSOL staking pages from S28-#26
    are deliberately untouched.
  - Every chunk lands with ``metadata.subkind="mev_tip_data"`` so we
    can disambiguate MEV-side vs staking-side Jito chunks at debug
    time and in retrieval-quality probes.
  - chunk_size=1000 per dispatch (larger than the 512 default — tip-
    floor JSON + bundle-mechanics docs benefit from contiguous
    context, and lower chunk count keeps the spend bounded).

Run:
    set -a; source .env; set +a   # MONGODB_URI + OPENAI_API_KEY
    uv run python scripts/protocol_native/ingest_jito_mev.py --dry-run
    uv run python scripts/protocol_native/ingest_jito_mev.py

Idempotent: ``source_id = UUID5(NAMESPACE_URL, "<endpoint_url>#<day_bucket>")``.
Re-running on the same calendar day produces 0 net new chunks via the
unique index on ``(source_id, chunk_index)``.

Budget: <=$0.50 per dispatch hard constraint. Empirical: 13 endpoints
with chunk_size=1000 produces ~30-60 chunks at text-embedding-3-small
prices (~$0.02/M tokens). Well inside budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import click
import httpx

# --- Minimal HTML -> text cleanup -----------------------------------------
# Same shape as scripts/protocol_native/ingest_protocol_native.py (sibling
# worktree). We don't pull in BeautifulSoup — keep deps narrow. Two passes:
# strip script/style blocks, then collapse tags + entities. Returns
# whitespace-collapsed prose that the embedder tokenizes happily.
_HTML_BLOCKS_TO_DROP = re.compile(
    r"<(script|style|noscript|svg|iframe|head)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")
_MULTI_WS = re.compile(r"\s+")

_ENTITY_MAP = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": " ",
    "ndash": "-",
    "mdash": "—",
    "hellip": "…",
}


def _decode_entity(m: re.Match[str]) -> str:
    raw = m.group(1)
    if raw.startswith(("#x", "#X")):
        try:
            return chr(int(raw[2:], 16))
        except ValueError:
            return " "
    if raw.startswith("#"):
        try:
            return chr(int(raw[1:]))
        except ValueError:
            return " "
    return _ENTITY_MAP.get(raw.lower(), " ")


def html_to_text(html: str) -> str:
    """Strip HTML to readable plaintext. Pure function."""
    if not html:
        return ""
    text = _HTML_BLOCKS_TO_DROP.sub(" ", html)
    text = _HTML_TAG.sub(" ", text)
    text = _HTML_ENTITY.sub(_decode_entity, text)
    text = _MULTI_WS.sub(" ", text).strip()
    # Cap at 40k chars; docs pages can be huge with inlined React state.
    return text[:40000]


_REPO = Path(__file__).resolve().parents[2]
_GC_SRC = _REPO / "packages" / "gecko-core" / "src"
if str(_GC_SRC) not in sys.path:
    sys.path.insert(0, str(_GC_SRC))

from gecko_core.db.mongo_chunks import insert_chunks_mongo  # noqa: E402
from gecko_core.ingestion.chunker import chunk as chunk_text  # noqa: E402
from gecko_core.ingestion.embedder import embed  # noqa: E402
from gecko_core.sources.jito_mev import (  # noqa: E402
    JITO_MEV_ENDPOINTS,
    JitoMevEndpoint,
    render_chunk,
)

log = logging.getLogger("protocol_native.ingest_jito_mev")

# Stable session namespace — all Jito-MEV protocol_native chunks belong
# to this session_id. Per Pattern F, retrieval is scoped by
# provider_kind + protocol + vertical, NOT session_id, so this is purely
# provenance metadata.
_JITO_MEV_SESSION = uuid5(NAMESPACE_URL, "gecko.protocol_native.jito_mev.session.v1")

# Per dispatch: chunk_size=1000. Larger than the default 512 because
# tip-floor JSON snapshots + bundle-mechanics docs reason better with
# contiguous context. 50-token overlap (default ratio scaled by ~10%).
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100


def _day_bucket(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


async def _fetch(client: httpx.AsyncClient, ep: JitoMevEndpoint) -> str | None:
    """Fetch one endpoint. Returns body text or None on failure/empty.

    Empty / placeholder bodies are dropped explicitly — re-creating the
    paysh_live `{"data":[]}` bug is exactly what we're trying to avoid.
    """
    try:
        headers = {
            "User-Agent": (
                "gecko-mcpay-api/1.0 (corpus-ingest s31-#50 jito-mev; +https://geckovision.tech)"
            ),
            "Accept": "application/json, text/html, text/markdown, */*",
        }
        resp = await client.get(ep.url, timeout=30.0, headers=headers, follow_redirects=True)
        if resp.status_code != 200:
            log.warning(
                "FETCH-FAIL %s status=%d body_head=%r",
                ep.slug,
                resp.status_code,
                resp.text[:200],
            )
            return None
        body = resp.text
        ctype = resp.headers.get("content-type", "").lower()
        if "application/json" in ctype:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, list) and len(parsed) > 40:
                    sample_note = (
                        f"NOTE: API returned {len(parsed)} entries; "
                        "showing first 40 for citation grounding. Full "
                        "telemetry available at the source URL."
                    )
                    parsed = [sample_note, *parsed[:40]]
                body = json.dumps(parsed, indent=2, sort_keys=True, ensure_ascii=False)
            except json.JSONDecodeError:
                pass
        elif "text/html" in ctype or body.lstrip().startswith("<"):
            cleaned = html_to_text(body)
            log.info(
                "HTML-CLEAN %s html_bytes=%d text_bytes=%d",
                ep.slug,
                len(body),
                len(cleaned),
            )
            body = cleaned
        # Empty / placeholder guard.
        if (
            not body
            or not body.strip()
            or body.strip()
            in (
                '{"data":[]}',
                "[]",
                "{}",
            )
        ):
            log.warning(
                "FETCH-EMPTY %s body=%r — skipping (would re-create paysh_live bug)",
                ep.slug,
                body[:100],
            )
            return None
        log.info(
            "FETCH-OK %s bytes=%d preview=%r",
            ep.slug,
            len(body),
            body[:120].replace("\n", " "),
        )
        return body
    except Exception as exc:
        log.warning("FETCH-ERR %s exc=%s", ep.slug, exc)
        return None


async def ingest_endpoint(
    ep: JitoMevEndpoint, *, dry_run: bool, http: httpx.AsyncClient
) -> dict[str, int]:
    """Fetch + render + chunk + embed + insert one endpoint."""
    now = datetime.now(UTC)
    day_iso = _day_bucket(now)

    body = await _fetch(http, ep)
    if body is None:
        return {"chunks": 0, "skipped": 1}

    rendered = render_chunk(ep, body, day_iso)
    chunks_list = chunk_text(rendered, size=_CHUNK_SIZE, overlap=_CHUNK_OVERLAP) or [rendered]
    log.info(
        "RENDER %s chunks=%d total_chars=%d chunk_size=%d",
        ep.slug,
        len(chunks_list),
        sum(len(c) for c in chunks_list),
        _CHUNK_SIZE,
    )

    if dry_run:
        return {"chunks": len(chunks_list), "skipped": 0}

    vectors, _tokens = await embed(chunks_list)
    rows: list[tuple[int, str, list[float]]] = [
        (i, chunks_list[i], list(vectors[i])) for i in range(len(chunks_list))
    ]

    source_key = f"protocol_native:jito_mev:{ep.slug}#{day_iso}"
    source_id = uuid5(NAMESPACE_URL, source_key)

    # Pattern F: protocol_native carries the exact protocol tag so the
    # protocol-exact retrieval boost stacks on top of the canon fallback.
    # vertical="dex" matches the existing Jito protocol_native chunks
    # (S28-#26) so MEV-side chunks surface alongside staking-side ones
    # under the same vertical filter; subkind="mev_tip_data" is the
    # disambiguator inside the Jito-protocol slice.
    inserted = await insert_chunks_mongo(
        session_id=_JITO_MEV_SESSION,
        source_id=source_id,
        chunks=rows,
        category="market_intelligence",
        vertical="dex",
        source="protocol_native",
        provider_kind="protocol_native",
        source_url=ep.url,
        freshness_tier="daily",
        protocol=("jito",),
        content_kind=ep.content_kind,  # type: ignore[arg-type]
        metadata_extra={"subkind": "mev_tip_data"},
    )
    log.info(
        "INSERT %s new_chunks=%d (day_bucket=%s) source_id=%s subkind=mev_tip_data",
        ep.slug,
        inserted,
        day_iso,
        str(source_id),
    )
    return {"chunks": inserted, "skipped": 0}


async def amain(*, endpoints: list[JitoMevEndpoint], dry_run: bool, sleep_seconds: float) -> int:
    log.info(
        "=== S31-#50 jito-mev ingest: %d endpoints (dry_run=%s chunk_size=%d) ===",
        len(endpoints),
        dry_run,
        _CHUNK_SIZE,
    )
    total_chunks = 0
    total_skipped = 0
    successes: list[str] = []
    failures: list[str] = []
    async with httpx.AsyncClient() as http:
        for i, ep in enumerate(endpoints, start=1):
            log.info("[%d/%d] %s", i, len(endpoints), ep.slug)
            stats = await ingest_endpoint(ep, dry_run=dry_run, http=http)
            total_chunks += stats["chunks"]
            total_skipped += stats["skipped"]
            if stats["chunks"] > 0:
                successes.append(ep.slug)
            else:
                failures.append(ep.slug)
            if i < len(endpoints):
                await asyncio.sleep(sleep_seconds)
    log.info(
        "=== DONE: endpoints=%d chunks=%d skipped=%d successes=%s failures=%s ===",
        len(endpoints),
        total_chunks,
        total_skipped,
        successes,
        failures,
    )
    return 0


@click.command()
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Fetch + render + chunk only; no embed, no Mongo writes.",
)
@click.option(
    "--sleep-seconds",
    type=float,
    default=1.0,
    show_default=True,
    help="Politeness delay between endpoint fetches.",
)
@click.option("--verbose", "-v", is_flag=True, default=False)
def main(dry_run: bool, sleep_seconds: float, verbose: bool) -> None:
    """S31-#50 — Jito MEV-tip ingest (separate from staking content)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )
    rc = asyncio.run(
        amain(
            endpoints=list(JITO_MEV_ENDPOINTS),
            dry_run=dry_run,
            sleep_seconds=sleep_seconds,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
