"""S31-#50 — Pattern E probe for the Jito MEV-tip ingest.

Per `feedback_wedge_reachability_check`: "Wired" != "reaches the model".
This script calls the production retrieval path
(`retrieve_trade_corpus_chunks`) with a question whose expected
citations include the new MEV-side Jito chunks, then counts how many
mev_tip_data subkind chunks land in the top-K result.

Run:
    set -a; source .env; set +a
    uv run python scripts/protocol_native/probe_jito_mev.py

Expected per dispatch: >=3 mev_tip_data chunks surface in top-10 for
the MEV-tip question.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_GC_SRC = _REPO / "packages" / "gecko-core" / "src"
if str(_GC_SRC) not in sys.path:
    sys.path.insert(0, str(_GC_SRC))

from gecko_core.db import get_chunk_store  # noqa: E402
from gecko_core.db.mongo import chunks_collection  # noqa: E402
from gecko_core.orchestration.trade_panel import (  # noqa: E402
    retrieve_trade_corpus_chunks,
)


async def amain() -> int:
    print(f"chunk_store={get_chunk_store()}")
    question = (
        "What's the right MEV tip floor on Solana right now? "
        "P50 vs P75 for high-frequency arb bundles on Jito?"
    )
    chunks = await retrieve_trade_corpus_chunks(
        idea=question,
        protocol="jito",
        vertical="dex",
        top_k=10,
    )
    print(f"\ntop-10 chunks returned: {len(chunks)}")
    # The retrieval function projects `metadata` but does not return it
    # into the result dicts — so for subkind counting we re-fetch each
    # chunk by id and read metadata.subkind directly. Same Mongo
    # collection, no separate retrieval path.
    coll = chunks_collection()
    mev_count = 0
    for i, c in enumerate(chunks, start=1):
        sub = ""
        if coll is not None and c.get("id"):
            try:
                from bson import ObjectId

                doc = await coll.find_one(
                    {"_id": ObjectId(c["id"])},
                    projection={"metadata": 1, "source_url": 1},
                )
                if doc:
                    sub = (doc.get("metadata") or {}).get("subkind") or ""
            except Exception:
                pass
        is_mev = sub == "mev_tip_data"
        if is_mev:
            mev_count += 1
        marker = "MEV" if is_mev else "   "
        print(
            f"  [{i:2d}] {marker} score={c.get('score', 0.0):.4f} "
            f"protocol={c.get('protocol')} pkind={c.get('provider_kind')} "
            f"subkind={sub!r} url={c.get('source_url', '')[:80]}"
        )
    print(f"\nmev_tip_data chunks in top-10: {mev_count}")
    print("PASS (>=3)" if mev_count >= 3 else "FAIL (<3)")
    return 0 if mev_count >= 3 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
