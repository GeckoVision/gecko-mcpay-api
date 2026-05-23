#!/usr/bin/env python3
"""Oracle gating-delta — does the REAL Gecko Oracle discriminate? (2026-05-22).

THE QUESTION (founder-prioritized, the win vs the V.0 local proxy)
  Phase V.0 (`docs/strategy/2026-05-22-gating-delta.md`) measured the contest
  bot's LOCAL deterministic gate (chart_analyst confidence ladder + regime +
  floor) and found it ANTI-PREDICTIVE on this window: gating delta -1.5%/-1.9%,
  CI-clean on the WRONG side. But that is the crude local proxy, NOT the
  product. We have NEVER measured whether the actual `gecko_trade_research`
  Oracle (adversarial 7-agent panel + grounded citations) discriminates.

  This script measures exactly that. For a bounded, regime-stratified sample of
  historical breakout entries, it calls the Oracle AS_OF the entry timestamp
  (S39-#133 point-in-time retrieval gate — the panel only sees corpus that
  existed at T, no look-ahead leakage), records the verdict (act / pass /
  defer + confidence + #citations), joins with the entry's real-exit forward
  PnL (the exact `exit_reconciliation` close-based stack), and computes:

    gating delta = netEV(SAFE) - netEV(DEFER u REJECT)

  with a PAIRED block-bootstrap CI (block=3, seed 1729 — matches
  `exit_reconciliation.block_bootstrap_ci`). SAFE = verdict "act"; DEFER u
  REJECT = "pass" or "defer".

WHAT IT REUSES (does NOT rebuild — V.0 scaffolding)
  - chart_floor_calibration : candidate detection, regime, enrich, horizon guard
  - exit_reconciliation     : simulate_exit_real_close (forward PnL), block
                              bootstrap CI, variance-inflation / N_eff
  - run_trade_panel_with_retrieval(as_of=...) : the real Oracle, point-in-time

BOUNDED SPEND
  --smoke (default N=3): replays the panel as_of a few cached entries, reports
  the actual per-call cost + latency. --full N=<N> scales to ~30. Cost is read
  off the same tiktoken estimator the panel emits on `oracle.cost_usd`, summed
  over the run. Basic tier (gpt-4o-mini) is the product's default trade tier.

READ-ONLY w.r.t. the live bot (port 8265). x402 stays STUB. No persistence:
  as_of retrieval is read-only Mongo; the panel writes nothing.

Usage:
    set -a && source .env && set +a
    uv run python scripts/trading_oracle/oracle_gating_delta.py --smoke
    uv run python scripts/trading_oracle/oracle_gating_delta.py --full 30 \\
        --json-out /tmp/oracle_gating_delta.json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import random
import statistics as st
import sys
import time
from dataclasses import asdict, dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
_CALIB = os.path.join(os.path.dirname(_HERE), "calibration")
sys.path.insert(0, _CALIB)

import chart_floor_calibration as base  # noqa: E402  faithful candidate gate
import exit_reconciliation as recon  # noqa: E402  real-exit PnL + block bootstrap

# ── Oracle invocation config ─────────────────────────────────────────
# `--gateway openai` mirrors the production local-dev path (gecko-mcp server
# `_run_trade_research`): llm_config from orchestration settings, OpenAI direct
# — the PRD oracle path. `--gateway openrouter` runs the SAME model through the
# OpenRouter gateway (fallback when the direct key is out of quota); the Oracle
# logic is byte-identical, only the HTTP gateway differs. See _build_llm_config.
VERTICAL = "dex"  # canonical trade vertical (memory: defi -> dex canon)
DEFAULT_TIER = "basic"  # gpt-4o-mini — the product's default trade tier
TOP_K = 15  # _DEFAULT_TRADE_TOP_K — the production retrieval width

# SAFE = the gate says "enter". The Oracle's "act" is the SAFE bucket;
# "pass"/"defer" are the DEFER u REJECT bucket. This is the literal-to-bucket
# map the gating delta is defined over.
SAFE_VERDICTS = {"act"}
GATE_OFF_VERDICTS = {"pass", "defer"}


def _idea_for(sym: str, regime: str) -> str:
    """The single-shot trade-judgment question the Oracle is built to answer
    (CLAUDE.md: Class-D single-shot judgment -> gecko_trade_research direct).
    A breakout just fired on `sym`; should we take the long entry now?"""
    return (
        f"A momentum breakout just fired on {sym} (a Solana token traded on DEXs): "
        f"price cleared its prior 24-bar high with a volume spike, current regime is "
        f"{regime}. Should I take a long entry right now, or wait?"
    )


# ── A graded entry: candidate + Oracle verdict + realized outcome ────
@dataclass
class GradedEntry:
    sym: str
    idx: int
    entry_ts_iso: str
    as_of: str  # YYYY-MM-DD point-in-time gate
    regime: str
    pnl_real: float  # realized gross pnl%, REAL close-based exit
    # Oracle envelope:
    verdict: str  # act / pass / defer (or "ERROR")
    confidence: float
    dissent_count: int
    n_evidence: int  # protocol/market-data citations (grounding test)
    n_framework: int  # canon citations (the lens)
    grounded: bool  # >=1 evidence citation -> a real, data-grounded gate
    latency_s: float
    cost_usd: float
    n_voice_fail: int = 0  # voices that errored (429/timeout) — degraded if high
    degraded: bool = False  # >=1 voice failed -> verdict is not a clean panel read
    error: str | None = None


# ── Candidate generation (V.0's faithful gate) ──────────────────────
@dataclass
class Cand:
    sym: str
    idx: int
    regime: str
    pnl_real: float
    entry_ts_ms: float


def collect_candidates(data: dict[str, dict]) -> list[Cand]:
    """All breakout/vol-spike candidates with a full forward horizon, in time
    order within each symbol. Identical gate to exit_reconciliation.collect, plus
    the entry timestamp (needed for the as_of gate)."""
    out: list[Cand] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = base.WARMUP
        while i < n:
            if (
                base.breakout_fires(c, i) or base.volume_spike_fires(c, i)
            ) and base.has_full_horizon(c, i):
                out.append(
                    Cand(
                        sym=sym,
                        idx=i,
                        regime=base.regime_at(c, i),
                        pnl_real=recon.simulate_exit_real_close(c, i),
                        entry_ts_ms=c["ts"][i],
                    )
                )
                i += 6
            else:
                i += 1
    return out


def stratified_sample(cands: list[Cand], n_target: int, seed: int = 1729) -> list[Cand]:
    """Stratify across TREND / TRANSITIONAL / CHOP, sampling proportional to each
    stratum's share but guaranteeing at least 1 per non-empty stratum. Within a
    stratum, sample without replacement (deterministic on seed)."""
    rng = random.Random(seed)
    by_reg: dict[str, list[Cand]] = {}
    for c in cands:
        by_reg.setdefault(c.regime, []).append(c)
    strata = [r for r in ("trend", "transitional", "chop") if by_reg.get(r)]
    total = sum(len(by_reg[r]) for r in strata)
    if total == 0:
        return []
    # Proportional allocation with a floor of 1 per stratum.
    alloc: dict[str, int] = {}
    for r in strata:
        alloc[r] = max(1, round(n_target * len(by_reg[r]) / total))
    # Trim/grow to hit n_target exactly (largest strata absorb the slack).
    while sum(alloc.values()) > n_target and any(alloc[r] > 1 for r in strata):
        r = max(strata, key=lambda x: alloc[x])
        if alloc[r] > 1:
            alloc[r] -= 1
    while sum(alloc.values()) < n_target:
        r = max(strata, key=lambda x: len(by_reg[x]) - alloc[x])
        if alloc[r] >= len(by_reg[r]):
            break
        alloc[r] += 1
    picked: list[Cand] = []
    for r in strata:
        pool = list(by_reg[r])
        rng.shuffle(pool)
        picked.extend(pool[: min(alloc[r], len(pool))])
    return picked


# ── Oracle call (point-in-time, real panel) ─────────────────────────
def _build_llm_config(gateway: str) -> tuple[dict, str]:
    """Build the panel llm_config. Returns (config, human_label).

    ``gateway="openai"`` byte-mirrors the production local-dev path (gecko-mcp
    server `_run_trade_research`): OpenAI direct, gpt-4o-mini, temp 0.3.

    ``gateway="openrouter"`` points the SAME model (`openai/gpt-4o-mini`) at the
    OpenRouter gateway. The Oracle's logic — prompts, 7-agent debate, retrieval,
    grounding gate — is byte-identical; only the HTTP gateway differs, and it
    serves the identical model. Used when the OpenAI direct key is out of quota
    (memory: feedback_openrouter_not_openai_for_new_llm — new LLM integrations,
    incl. eval harnesses, route through OpenRouter). The doc records which
    gateway served the run.
    """
    if gateway == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError("gateway=openrouter requires OPENROUTER_API_KEY in env")
        cfg = {
            "config_list": [
                {
                    "model": "openai/gpt-4o-mini",
                    "api_key": key,
                    "base_url": "https://openrouter.ai/api/v1",
                    "default_headers": {
                        "HTTP-Referer": "https://geckovision.tech",
                        "X-Title": "Gecko-Oracle-Eval",
                    },
                }
            ],
            "temperature": 0.3,
        }
        return cfg, "openrouter:openai/gpt-4o-mini"

    from gecko_core.orchestration.settings import get_orchestration_settings

    orch = get_orchestration_settings()
    cfg = {
        "config_list": [
            {
                "model": "gpt-4o-mini",
                "api_key": orch.llm_api_key,
                "base_url": orch.llm_endpoint,
            }
        ],
        "temperature": 0.3,
    }
    return cfg, "openai-direct:gpt-4o-mini"


def _estimate_cost(verdict, idea: str, tier: str) -> float:
    """Re-derive the panel's own cost estimate from the returned turns + seed.
    Matches run_trade_panel's tiktoken accounting (seed shared across voices;
    each voice sees seed + prior turns)."""
    try:
        from gecko_core.routing.costs import estimate_cost_usd, estimate_tokens

        # We don't have the exact retrieved_chunks the seed was built from, but
        # the seed is dominated by chunk text; reconstruct from the verdict's
        # citation snippets as a lower-bound proxy for the chunk payload.
        snippets = [
            c.snippet for c in (verdict.evidence_citations + verdict.framework_context) if c.snippet
        ]
        seed_proxy = idea + "\n" + "\n".join(snippets)
        seed_tokens = estimate_tokens(seed_proxy)
        turn_tokens = [estimate_tokens(t.content) for t in verdict.turns]
        tokens_in = 0
        accum = seed_tokens
        for tt in turn_tokens:
            tokens_in += accum
            accum += tt
        tokens_out = sum(turn_tokens)
        model_id = "gpt-4o" if tier == "pro" else "gpt-4o-mini"
        return round(estimate_cost_usd(model_id, tokens_in=tokens_in, tokens_out=tokens_out), 6)
    except Exception:
        return float("nan")


async def grade_entry(cand: Cand, *, tier: str, llm_config: dict) -> GradedEntry:
    """Call the Oracle as_of the entry timestamp; record the verdict envelope."""
    from gecko_core.orchestration.trade_panel import run_trade_panel_with_retrieval

    entry_dt = dt.datetime.fromtimestamp(cand.entry_ts_ms / 1000, dt.UTC)
    as_of = entry_dt.date().isoformat()
    idea = _idea_for(cand.sym, cand.regime)
    t0 = time.monotonic()
    try:
        verdict = await run_trade_panel_with_retrieval(
            idea=idea,
            protocol=cand.sym.lower(),  # ticker as protocol handle; canon passes via null-match
            vertical=VERTICAL,
            tier=tier,
            top_k=TOP_K,
            llm_config=llm_config,
            as_of=as_of,  # S39-#133 point-in-time gate — no look-ahead
        )
        latency = time.monotonic() - t0
        n_ev = len(verdict.evidence_citations)
        n_fw = len(verdict.framework_context)
        # Degraded-run detection: the panel marks a failed voice with content
        # "(voice failed: ...)". If ANY voice failed, the coordinator's verdict
        # is synthesized from a partial transcript — not a clean panel read.
        n_fail = sum(1 for t in verdict.turns if t.content.startswith("(voice failed"))
        return GradedEntry(
            sym=cand.sym,
            idx=cand.idx,
            entry_ts_iso=entry_dt.strftime("%Y-%m-%d %H:%M"),
            as_of=as_of,
            regime=cand.regime,
            pnl_real=cand.pnl_real,
            verdict=verdict.verdict,
            confidence=verdict.confidence,
            dissent_count=verdict.dissent_count,
            n_evidence=n_ev,
            n_framework=n_fw,
            grounded=n_ev >= 1,
            latency_s=latency,
            cost_usd=_estimate_cost(verdict, idea, tier),
            n_voice_fail=n_fail,
            degraded=n_fail > 0,
        )
    except Exception as exc:
        latency = time.monotonic() - t0
        return GradedEntry(
            sym=cand.sym,
            idx=cand.idx,
            entry_ts_iso=entry_dt.strftime("%Y-%m-%d %H:%M"),
            as_of=as_of,
            regime=cand.regime,
            pnl_real=cand.pnl_real,
            verdict="ERROR",
            confidence=0.0,
            dissent_count=0,
            n_evidence=0,
            n_framework=0,
            grounded=False,
            latency_s=latency,
            cost_usd=float("nan"),
            error=f"{type(exc).__name__}: {exc}",
        )


# ── Paired block-bootstrap gating delta ─────────────────────────────
def _series_by_sym(entries: list[GradedEntry], bucket: set[str]) -> dict[str, list[float]]:
    """Per-symbol ordered gross-PnL series for entries whose verdict is in
    `bucket`. Ordered within symbol by idx (preserves serial dependence for
    the block bootstrap)."""
    by_sym: dict[str, list[float]] = {}
    for e in sorted(entries, key=lambda x: (x.sym, x.idx)):
        if e.verdict in bucket:
            by_sym.setdefault(e.sym, []).append(e.pnl_real)
    return by_sym


def gating_delta_paired_ci(
    entries: list[GradedEntry],
    *,
    block: int = recon.BLOCK_LEN,
    n_boot: int = recon.N_BOOTSTRAP,
    alpha: float = 0.05,
    seed: int = recon.RNG_SEED,
) -> dict:
    """Δ = mean(SAFE) - mean(DEFER u REJECT), with a PAIRED moving-block
    bootstrap CI. Both arms are resampled on the SAME bootstrap draw (the two
    arms are disjoint partitions of one sample, so a paired resample keeps the
    SAFE/GATE-OFF split fixed and propagates the shared sampling noise). Fee
    cancels in the difference, so Δ is computed gross.

    Resampling unit: per-symbol blocks. Each iteration, for the union of
    symbols, draw overlapping length-`block` blocks (random start within each
    symbol's COMBINED ordered entry list) until the resample reaches the original
    count, then split each resampled entry back into its arm by its verdict
    bucket and recompute both means. This preserves within-symbol autocorrelation
    AND the pairing."""
    graded = [e for e in entries if e.verdict in (SAFE_VERDICTS | GATE_OFF_VERDICTS)]
    safe = [e for e in graded if e.verdict in SAFE_VERDICTS]
    gate_off = [e for e in graded if e.verdict in GATE_OFF_VERDICTS]
    safe_pnl = [e.pnl_real for e in safe]
    off_pnl = [e.pnl_real for e in gate_off]
    out: dict = {
        "n_safe": len(safe),
        "n_gate_off": len(gate_off),
        "mean_safe": st.mean(safe_pnl) if safe_pnl else float("nan"),
        "mean_gate_off": st.mean(off_pnl) if off_pnl else float("nan"),
    }
    if not safe_pnl or not off_pnl:
        out["delta"] = float("nan")
        out["ci"] = [float("nan"), float("nan")]
        out["ci_clean"] = "n/a"
        out["note"] = "one arm empty — gating delta undefined"
        return out

    point = st.mean(safe_pnl) - st.mean(off_pnl)
    # Per-symbol COMBINED ordered (pnl, is_safe) tuples.
    by_sym: dict[str, list[tuple[float, bool]]] = {}
    for e in sorted(graded, key=lambda x: (x.sym, x.idx)):
        by_sym.setdefault(e.sym, []).append((e.pnl_real, e.verdict in SAFE_VERDICTS))
    usable = [s for s in by_sym.values() if s]
    weights = [len(s) for s in usable]
    total = sum(weights)
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        sample: list[tuple[float, bool]] = []
        while len(sample) < total:
            s = rng.choices(usable, weights=weights, k=1)[0]
            b = min(block, len(s))
            start = rng.randrange(0, len(s) - b + 1)
            sample.extend(s[start : start + b])
        sample = sample[:total]
        bs = [p for p, is_safe in sample if is_safe]
        bo = [p for p, is_safe in sample if not is_safe]
        if not bs or not bo:
            continue  # degenerate draw — skip (rare at reasonable arm sizes)
        boots.append(st.mean(bs) - st.mean(bo))
    if not boots:
        out["delta"] = point
        out["ci"] = [float("nan"), float("nan")]
        out["ci_clean"] = "n/a"
        out["note"] = "all bootstrap draws degenerate (an arm too small)"
        return out
    boots.sort()
    lo = boots[int((alpha / 2) * len(boots))]
    hi = boots[int((1 - alpha / 2) * len(boots))]
    out["delta"] = point
    out["ci"] = [lo, hi]
    out["ci_clean"] = "YES(+)" if lo > 0 else ("YES(-)" if hi < 0 else "no")
    out["n_boot_valid"] = len(boots)
    return out


# ── Reporting ───────────────────────────────────────────────────────
def _verdict_dist(entries: list[GradedEntry]) -> dict[str, int]:
    d: dict[str, int] = {}
    for e in entries:
        d[e.verdict] = d.get(e.verdict, 0) + 1
    return d


def print_report(entries: list[GradedEntry], *, tier: str, gateway: str) -> dict:
    errs = [e for e in entries if e.verdict == "ERROR"]
    degraded = [e for e in entries if e.verdict != "ERROR" and e.degraded]
    # The gating delta is computed ONLY over CLEAN panel reads: no transport
    # error AND no failed voice. A degraded verdict (partial transcript) is not
    # a real gate, same principle as ungrounded.
    graded = [e for e in entries if e.verdict != "ERROR" and not e.degraded]
    dist = _verdict_dist(entries)
    clean_dist = _verdict_dist(graded)
    total_cost = sum(e.cost_usd for e in entries if e.cost_usd == e.cost_usd)
    latencies = [e.latency_s for e in entries]
    grounded = [e for e in graded if e.grounded]

    print(f"\n{'=' * 96}")
    print(f"ORACLE GATING DELTA — does the real Oracle discriminate?  (tier={tier}, gw={gateway})")
    print(f"{'=' * 96}")
    print(
        f"  entries attempted: {len(entries)}  (transport errors: {len(errs)}, "
        f"degraded/partial-panel: {len(degraded)})"
    )
    print(f"  verdict distribution (all): {dist}")
    print(f"  verdict distribution (CLEAN panels only): {clean_dist}")
    print(
        f"  grounded (>=1 evidence citation): {len(grounded)}/{len(graded)} "
        f"({100 * len(grounded) / len(graded) if graded else 0:.0f}%) "
        f"-> ungrounded: {len(graded) - len(grounded)} (canon-only / no real data gate)"
    )
    print(
        f"  total estimated spend: ${total_cost:.4f}   "
        f"per-call mean: ${total_cost / max(1, len(entries)):.5f}"
    )
    if latencies:
        print(
            f"  latency: mean={st.mean(latencies):.1f}s  "
            f"min={min(latencies):.1f}s  max={max(latencies):.1f}s"
        )

    # Per-entry table.
    print(
        f"\n  {'sym':>6} {'as_of':>11} {'regime':>13} {'verdict':>7} "
        f"{'conf':>5} {'diss':>4} {'ev':>3} {'fw':>3} {'pnl%':>7} {'$':>8} {'lat_s':>6} {'flag':>9}"
    )
    print("  " + "-" * 100)
    for e in sorted(entries, key=lambda x: (x.regime, x.sym, x.idx)):
        if e.verdict == "ERROR":
            continue
        cost = "  err" if e.cost_usd != e.cost_usd else f"{e.cost_usd:.5f}"
        flag = f"DEGR{e.n_voice_fail}/7" if e.degraded else ("" if e.grounded else "ungrnd")
        print(
            f"  {e.sym:>6} {e.as_of:>11} {e.regime:>13} {e.verdict:>7} "
            f"{e.confidence:>5.2f} {e.dissent_count:>4} {e.n_evidence:>3} {e.n_framework:>3} "
            f"{e.pnl_real:>+7.2f} {cost:>8} {e.latency_s:>6.1f} {flag:>9}"
        )
    for e in errs:
        print(f"  {e.sym:>6} {e.as_of:>11} {e.regime:>13}   ERROR -> {e.error}")

    # Gating delta — overall + per regime.
    print(f"\n{'=' * 96}")
    print("GATING DELTA  Δ = netEV(SAFE='act') - netEV(DEFER u REJECT='pass'/'defer')")
    print(
        f"  paired moving-block bootstrap: block={recon.BLOCK_LEN}, "
        f"n_boot={recon.N_BOOTSTRAP}, seed={recon.RNG_SEED}, gross (fee cancels)"
    )
    print(f"{'=' * 96}")
    hdr = (
        f"  {'scope':>14} {'nSAFE':>5} {'nOFF':>5} | {'mSAFE%':>8} {'mOFF%':>8} | "
        f"{'Δ%':>8} {'paired 95% CI':>22} {'clean':>7}"
    )
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    results: dict = {}
    scopes = [("ALL", None), ("trend", "trend"), ("transitional", "transitional"), ("chop", "chop")]
    for label, rg in scopes:
        subset = [e for e in graded if rg is None or e.regime == rg]
        gd = gating_delta_paired_ci(subset)
        results[label] = gd
        if gd["delta"] != gd["delta"]:  # nan
            print(
                f"  {label:>14} {gd['n_safe']:>5} {gd['n_gate_off']:>5} | "
                f"{'—':>8} {'—':>8} | {'—':>8} {gd.get('note', 'undefined'):>22}"
            )
            continue
        ci = gd["ci"]
        print(
            f"  {label:>14} {gd['n_safe']:>5} {gd['n_gate_off']:>5} | "
            f"{gd['mean_safe']:>+8.3f} {gd['mean_gate_off']:>+8.3f} | "
            f"{gd['delta']:>+8.3f} [{ci[0]:>+7.3f},{ci[1]:>+7.3f}] {gd['ci_clean']:>7}"
        )

    # N_eff for the graded pool (autocorrelation honesty, V.0 method).
    gross_series = list(
        recon.regime_series_gross(
            [
                recon.Cand(e.sym, e.idx, e.regime, 0.0, False, e.pnl_real, e.pnl_real)
                for e in graded
            ],
            None,
            "pnl_real",
        )
    )
    vif = recon.variance_inflation(gross_series)
    n = sum(len(s) for s in gross_series)
    print(f"\n  graded pool: N={n}  VIF={vif:.2f}  N_eff={n / vif if vif else n:.0f}")

    return {
        "gateway": gateway,
        "verdict_dist_all": dist,
        "verdict_dist_clean": clean_dist,
        "gating_delta": results,
        "n_clean": len(graded),
        "n_errors": len(errs),
        "n_degraded": len(degraded),
        "n_grounded": len(grounded),
        "total_cost_usd": total_cost,
        "vif": vif,
        "n_eff": n / vif if vif else n,
    }


# ── Driver ──────────────────────────────────────────────────────────
async def run(args) -> None:
    with open(args.window) as f:
        raw = json.load(f)
    print(f"Loaded cached candles from {args.window}", file=sys.stderr)
    data = {sym: base.enrich(cs) for sym, cs in raw.items() if len(cs) >= 60}
    base.print_window_summary(data)

    cands = collect_candidates(data)
    by_reg: dict[str, int] = {}
    for c in cands:
        by_reg[c.regime] = by_reg.get(c.regime, 0) + 1
    print(
        f"\nTotal candidates (deterministic gate, full-horizon): {len(cands)}  by regime: {by_reg}"
    )

    n_target = 3 if args.smoke else args.full
    sample = stratified_sample(cands, n_target, seed=args.seed)
    samp_reg: dict[str, int] = {}
    for c in sample:
        samp_reg[c.regime] = samp_reg.get(c.regime, 0) + 1
    print(f"Sampled {len(sample)} entries (target {n_target}), stratified: {samp_reg}")

    if args.smoke:
        print("\n*** SMOKE MODE — N=3, measuring per-call cost + latency before scaling ***")

    llm_config, gw_label = _build_llm_config(args.gateway)
    print(f"LLM gateway: {gw_label}  (tier={args.tier})", file=sys.stderr)
    entries: list[GradedEntry] = []
    for k, cand in enumerate(sample, 1):
        print(
            f"  [{k}/{len(sample)}] {cand.sym} @ {dt.datetime.fromtimestamp(cand.entry_ts_ms / 1000, dt.UTC):%Y-%m-%d %H:%M} "
            f"regime={cand.regime} ...",
            file=sys.stderr,
            flush=True,
        )
        e = await grade_entry(cand, tier=args.tier, llm_config=llm_config)
        status = e.verdict if e.verdict != "ERROR" else f"ERROR({e.error})"
        flag = f" [DEGRADED {e.n_voice_fail}/7 voices failed]" if e.degraded else ""
        print(
            f"      -> {status} conf={e.confidence:.2f} ev={e.n_evidence} fw={e.n_framework} "
            f"pnl={e.pnl_real:+.2f}% {e.latency_s:.1f}s ${e.cost_usd:.5f}{flag}",
            file=sys.stderr,
            flush=True,
        )
        entries.append(e)

    summary = print_report(entries, tier=args.tier, gateway=gw_label)

    if args.json_out:
        out = {
            "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "window": args.window,
            "tier": args.tier,
            "mode": "smoke" if args.smoke else "full",
            "n_target": n_target,
            "vertical": VERTICAL,
            "top_k": TOP_K,
            "safe_verdicts": sorted(SAFE_VERDICTS),
            "gate_off_verdicts": sorted(GATE_OFF_VERDICTS),
            "summary": summary,
            "entries": [asdict(e) for e in entries],
        }
        with open(args.json_out, "w") as f:
            json.dump(out, f, indent=2, default=str)
        print(f"\nWrote {args.json_out}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--window", default="/tmp/cal_candles_d1.json", help="cached candle window JSON"
    )
    ap.add_argument("--smoke", action="store_true", help="N=3 feasibility + cost/latency probe")
    ap.add_argument(
        "--full", type=int, default=30, help="N for the full sweep (ignored under --smoke)"
    )
    ap.add_argument("--tier", default=DEFAULT_TIER, choices=["basic", "pro"])
    ap.add_argument(
        "--gateway",
        default="openai",
        choices=["openai", "openrouter"],
        help="LLM gateway. 'openai' = production direct path; 'openrouter' = same "
        "model (openai/gpt-4o-mini) via OpenRouter when the direct key is "
        "out of quota.",
    )
    ap.add_argument("--seed", type=int, default=1729)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
