"""The verdict ledger — the moat's first row.

``record_firewall_verdict`` writes ONE row per pre-trade verdict in the LOCKED
``firewall_verdicts`` schema (see :class:`FirewallVerdict`). The row is committed
*before* the launch resolves; ``resolved_outcome`` / ``verdict_correct`` are
``None`` at commit and backfilled later by an outcome-grading batch job (MISSING
today, by design — this is the seam it will write into).

Persistence (REUSE, do not invent):
  * Mongo when ``MONGODB_URI`` is configured — via the existing
    ``gecko_core.db.mongo`` client/conn pattern, into a *namespaced* collection
    ``firewall_verdicts`` (NOT a prod collection). The DB name is the dev-scoped
    ``MONGODB_FIREWALL_DB`` (default ``gecko_firewall_dev``) so the slice can NEVER
    write into the prod ``gecko_rag`` chunk store.
  * ELSE a local JSONL dev artifact at ``/tmp/gecko-firewall-verdicts.jsonl`` —
    same schema, clearly a dev fallback.

The chosen sink is reported back on every call so a run is never ambiguous about
where its rows landed.

``envelope_hash`` REUSES ``gecko_core.payments.receipt.hash.receipt_hash`` — the
published canonical-hash contract. We do NOT invent a hash here.

Hotpath note: this module is NOT on the latency island. It is the ledger seam the
*serve* result flows into after the gate decision — importing ``gecko_core.db`` is
fine here (the hotpath ban applies to ``trade_agent.hotpath``, not this package).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.payments.receipt.hash import receipt_hash

logger = logging.getLogger(__name__)

# Namespaced, dev-scoped — NEVER a prod collection / DB. The DB default is
# deliberately *not* the chunk-store ``gecko_rag`` DB.
FIREWALL_VERDICTS_COLLECTION = "firewall_verdicts"
FIREWALL_DB_DEFAULT = "gecko_firewall_dev"
FIREWALL_DB_ENV = "MONGODB_FIREWALL_DB"

# The dev JSONL fallback artifact (used when Mongo is not configured).
JSONL_FALLBACK_PATH = Path("/tmp/gecko-firewall-verdicts.jsonl")

# Engine / signal provenance stamped on every row so a later grading job can
# bucket verdicts by the code that produced them. Bump when the fused-signal set
# or the gate kernel changes in a way that would change a verdict for the same
# inputs. (Two-way until rows are graded; pinned here for the slice.)
ENGINE_VERSION = "firewall-engine@2026-06"
SIGNAL_VERSION = "snipe+wash@2026-06"

# Provenance of the underlying chain data. The slice is fork-only.
VerdictSource = Literal["fork", "live", "fixture"]


class FirewallVerdict(BaseModel):
    """ONE ``firewall_verdicts`` row — the LOCKED schema (one-way-door contract).

    Field names are verbatim from the architecture doc + the build spec. Do NOT
    rename: rows written now will be graded for months, and a verifier recomputes
    ``envelope_hash`` from the same projection. The grading fields
    (``resolved_outcome`` … ``verdict_correct``) are ``None`` at commit and
    backfilled by the outcome-grading job.
    """

    model_config = ConfigDict(extra="forbid")

    verdict_id: str = Field(..., description="Stable id for this verdict row (idempotency key).")
    mint: str
    pool: str | None = Field(default=None, description="Pool / AMM address, when known.")

    # The decision surface.
    gate: str = Field(..., description="block / caution / ok / unknown.")
    snipe_label: str | None = Field(default=None)
    snipe_fired: list[str] = Field(default_factory=list)
    wash_label: str | None = Field(default=None)
    wash_fired: list[str] = Field(default_factory=list)

    # When the verdict was committed + how old the launch was at that moment.
    committed_at: float = Field(..., description="Unix epoch seconds at commit.")
    launch_age_s: float | None = Field(
        default=None, description="Seconds since pool creation at commit time."
    )
    commitment: str = Field(default="confirmed")

    # The receipt commitment over the decision surface (reuses receipt/hash.py).
    envelope_hash: str = Field(..., description="sha256 of the canonical verdict envelope.")

    engine_version: str = Field(default=ENGINE_VERSION)
    signal_version: str = Field(default=SIGNAL_VERSION)

    source: VerdictSource = Field(..., description='"fork" | "live" | "fixture".')

    # Optional on-chain anchor — null unless a devnet receipt was anchored.
    receipt_sig: str | None = Field(default=None)

    # Graded LATER — null at commit. The outcome-grading job backfills these.
    resolved_outcome: str | None = Field(default=None)
    resolved_at: float | None = Field(default=None)
    outcome_metrics: dict[str, Any] | None = Field(default=None)
    verdict_correct: bool | None = Field(default=None)


def _firewall_db_name(env: Mapping[str, str] | None = None) -> str:
    src = env if env is not None else os.environ
    return src.get(FIREWALL_DB_ENV, FIREWALL_DB_DEFAULT)


def _firewall_collection() -> Any | None:
    """Return the dev-scoped ``firewall_verdicts`` motor collection, or None.

    Reuses the shared ``gecko_core.db.mongo`` client (one ``AsyncIOMotorClient``
    per process, lru_cached) but points at the dev firewall DB — NEVER the prod
    chunk-store DB. Returns None when ``MONGODB_URI`` is unset or motor missing.
    """
    from gecko_core.db.mongo import _client

    client = _client()
    if client is None:
        return None
    return client[_firewall_db_name()][FIREWALL_VERDICTS_COLLECTION]


def envelope_for_verdict(
    *,
    mint: str,
    gate: str,
    snipe_label: str | None,
    snipe_fired: list[str],
    wash_label: str | None,
    wash_fired: list[str],
) -> dict[str, Any]:
    """Build the verdict ENVELOPE that ``envelope_hash`` commits to.

    Shaped to the receipt-hash spec's four spec fields (``verdict`` /
    ``confidence`` / ``citations`` / ``dissent``) so ``receipt_hash`` projects it
    deterministically. The firewall has no panel citations, so:
      * ``verdict``    = the gate token (block/caution/ok/unknown),
      * ``confidence`` = 1.0 (the gate is deterministic, not probabilistic),
      * ``dissent``    = the fired signals, each as a one-line dissent row
        (``voice`` = the signal family, ``verbatim`` = the signal code) so the
        commitment binds to WHICH signals drove the gate, not just the label.
    """
    dissent: list[dict[str, str]] = [
        {"voice": "snipe", "stance": snipe_label or "", "verbatim": code, "on_topic": "true"}
        for code in snipe_fired
    ] + [
        {"voice": "wash", "stance": wash_label or "", "verbatim": code, "on_topic": "true"}
        for code in wash_fired
    ]
    return {
        "verdict": gate,
        "confidence": 1.0,
        "citations": [{"id": mint, "source": "firewall", "url": ""}],
        "dissent": dissent,
    }


async def record_firewall_verdict(
    *,
    mint: str,
    gate: str,
    snipe_label: str | None = None,
    snipe_fired: list[str] | None = None,
    wash_label: str | None = None,
    wash_fired: list[str] | None = None,
    pool: str | None = None,
    launch_age_s: float | None = None,
    source: VerdictSource = "fork",
    receipt_sig: str | None = None,
    committed_at: float | None = None,
    verdict_id: str | None = None,
) -> tuple[FirewallVerdict, str]:
    """Write ONE ``firewall_verdicts`` row and return ``(row, sink)``.

    ``sink`` is ``"mongo:<db>.<coll>"`` or ``"jsonl:<path>"`` so the caller can
    report exactly where the row landed. Grading fields are left ``None`` (this is
    the commit, not the resolution). Mongo failures fall back to JSONL with the
    error surfaced verbatim in the sink string — never a silent success.
    """
    snipe_fired = list(snipe_fired or [])
    wash_fired = list(wash_fired or [])
    now = committed_at if committed_at is not None else time.time()

    envelope = envelope_for_verdict(
        mint=mint,
        gate=gate,
        snipe_label=snipe_label,
        snipe_fired=snipe_fired,
        wash_label=wash_label,
        wash_fired=wash_fired,
    )
    env_hash = receipt_hash(envelope)
    vid = verdict_id or f"fw-{int(now)}-{env_hash[:12]}"

    row = FirewallVerdict(
        verdict_id=vid,
        mint=mint,
        pool=pool,
        gate=gate,
        snipe_label=snipe_label,
        snipe_fired=snipe_fired,
        wash_label=wash_label,
        wash_fired=wash_fired,
        committed_at=now,
        launch_age_s=launch_age_s,
        commitment="confirmed",
        envelope_hash=env_hash,
        source=source,
        receipt_sig=receipt_sig,
    )

    coll = _firewall_collection()
    if coll is not None:
        try:
            doc = row.model_dump(mode="json")
            await coll.update_one(
                {"verdict_id": vid}, {"$set": doc}, upsert=True
            )  # idempotent on verdict_id
            sink = f"mongo:{_firewall_db_name()}.{FIREWALL_VERDICTS_COLLECTION}"
            logger.info("firewall.ledger wrote row id=%s sink=%s gate=%s", vid, sink, gate)
            return row, sink
        except Exception as exc:  # surface verbatim; then fall through to JSONL
            logger.warning("firewall.ledger mongo write FAILED (%s) — JSONL fallback", exc)
            sink_note = f" (mongo failed: {type(exc).__name__}: {exc})"
    else:
        sink_note = ""

    # JSONL dev fallback — append one line, same schema.
    JSONL_FALLBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JSONL_FALLBACK_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")
    sink = f"jsonl:{JSONL_FALLBACK_PATH}{sink_note}"
    logger.info("firewall.ledger wrote row id=%s sink=%s gate=%s", vid, sink, gate)
    return row, sink


async def read_firewall_verdicts(mint: str | None = None) -> list[FirewallVerdict]:
    """Read rows back (Mongo or JSONL) — used by the assert step to verify commit.

    Filters by ``mint`` when given. Returns parsed :class:`FirewallVerdict` rows.
    """
    coll = _firewall_collection()
    if coll is not None:
        query: dict[str, Any] = {"mint": mint} if mint else {}
        cursor = coll.find(query)
        docs = await cursor.to_list(length=1000)
        return [FirewallVerdict.model_validate(_strip_mongo_id(d)) for d in docs]

    if not JSONL_FALLBACK_PATH.exists():
        return []
    rows: list[FirewallVerdict] = []
    for line in JSONL_FALLBACK_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = FirewallVerdict.model_validate_json(line)
        if mint is None or row.mint == mint:
            rows.append(row)
    return rows


def _strip_mongo_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc.pop("_id", None)
    return doc


__all__ = [
    "ENGINE_VERSION",
    "FIREWALL_DB_DEFAULT",
    "FIREWALL_VERDICTS_COLLECTION",
    "JSONL_FALLBACK_PATH",
    "SIGNAL_VERSION",
    "FirewallVerdict",
    "envelope_for_verdict",
    "read_firewall_verdicts",
    "record_firewall_verdict",
]
