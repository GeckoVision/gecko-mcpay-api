"""W3 — Information-MEV proof-library gallery.

Runs the LIVE Information-MEV detector over real Solana mints and writes the
"caught what the venue rated Normal" collateral for the MEV-decision-provider
thesis. The path exercised is the exact production one:

    CoinGecko on-chain (mcap + DEX liquidity)
        -> compute_manipulation_signals  (ratio + flags, PR #136)
        -> assess_information_mev         (named score/label/reasons, W1)

No API key, no RPC: the market-manipulation read is CoinGecko free-tier only.
Holder concentration (the full safety read's *other* axis) is NOT fetched here
— the market signal alone catches the BrCA-class fake-market-cap pattern; the
live verdict path adds concentration via QuickNode/Helius.

Run:
    uv run python scripts/analysis/information_mev_gallery.py

Outputs:
    - stdout: public-safe summary table
    - private/strategy/2026-06-14-information-mev-gallery.md (gitignored): full gallery
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from gecko_core.orchestration.trade_panel.models import InformationMEVBlock
from gecko_core.orchestration.trade_panel.safety_check import (
    assess_information_mev,
    compute_manipulation_signals,
)
from gecko_core.sources.coingecko import CoinGeckoClient, OnchainTokenMarket


@dataclass
class Candidate:
    name: str
    mint: str
    venue_rating: str  # what a mainstream tool/venue shows — the contrast
    note: str = ""


# Seed set. BrCA is the hero case (owner-acknowledged bot price-inflation; a
# mainstream rating called it "Normal"). The majors are deep-liquidity CONTROLS
# — they must come back 'clean', or the detector has a false-positive problem.
# Add more candidate mints here as they're identified.
CANDIDATES: list[Candidate] = [
    Candidate(
        "Brazil Carbon Asset (BrCA)",
        "BCAxFqs3VJGTmVsBsyYxWL2zZG6xR1kAynCKkhBKEkxx",
        "DexView: Normal",
        "RWA carbon credit; owner publicly acknowledges bots inflating price for sell timing.",
    ),
    Candidate(
        "Jupiter (JUP)",
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "—",
        "deep-liquidity control",
    ),
    Candidate(
        "Bonk (BONK)", "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", "—", "deep-liquidity control"
    ),
    Candidate(
        "JitoSOL", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn", "—", "deep-liquidity control"
    ),
    Candidate(
        "dogwifhat (WIF)",
        "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "—",
        "deep-liquidity control",
    ),
]


@dataclass
class Row:
    candidate: Candidate
    mcap: float | None
    liquidity: float | None
    ratio_pct: float | None
    flags: list[str] = field(default_factory=list)
    imev: InformationMEVBlock | None = None
    error: str | None = None


def _usd(v: float | None) -> str:
    if v is None:
        return "n/a"
    if v >= 1_000_000:
        return f"${v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v / 1_000:.1f}K"
    return f"${v:.0f}"


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}%"


def _label(row: Row) -> str:
    if row.error:
        return f"ERROR({row.error})"
    if row.imev is None:
        return "no-read"
    return f"{row.imev.label} ({row.imev.score:.2f})"


async def _assess(client: CoinGeckoClient, c: Candidate) -> Row:
    try:
        market: OnchainTokenMarket | None = await client.onchain_token_market(
            c.mint, network="solana"
        )
        mcap, liq, ratio, flags = compute_manipulation_signals(market)
        imev = assess_information_mev(
            market_cap_usd=mcap,
            liquidity_usd=liq,
            ratio_pct=ratio,
            manip_flags=flags,
            top_holder_pct=None,
        )
        return Row(c, mcap, liq, ratio, flags, imev)
    except Exception as exc:  # pragma: no cover - network/CLI tool
        return Row(c, None, None, None, error=type(exc).__name__)


def _render_gallery(rows: list[Row]) -> str:
    lines: list[str] = [
        "# Information-MEV Proof Library (2026-06-14)",
        "",
        "Live detector run — CoinGecko on-chain mcap/liquidity → manipulation signals → "
        "named Information-MEV verdict. Market signal only (no holder concentration).",
        "",
        "| Token | Venue rating | Market cap | Liquidity | Liq/Mcap | Verdict | Flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        flags = ", ".join(r.flags) if r.flags else "—"
        lines.append(
            f"| {r.candidate.name} | {r.candidate.venue_rating} | {_usd(r.mcap)} | "
            f"{_usd(r.liquidity)} | {_pct(r.ratio_pct)} | **{_label(r)}** | {flags} |"
        )
    lines.append("")
    lines.append("## Cases")
    for r in rows:
        lines.append("")
        lines.append(f"### {r.candidate.name} — `{r.candidate.mint}`")
        lines.append(f"- {r.candidate.note}")
        lines.append(f"- Mainstream rating: **{r.candidate.venue_rating}**")
        lines.append(
            f"- On-chain: mcap {_usd(r.mcap)} / liquidity {_usd(r.liquidity)} = {_pct(r.ratio_pct)}"
        )
        if r.imev is not None:
            lines.append(
                f"- **Gecko Information-MEV verdict: {r.imev.label} (score {r.imev.score:.2f})**"
            )
            for reason in r.imev.reasons:
                lines.append(f"  - {reason}")
        elif r.error:
            lines.append(f"- read error: {r.error}")
        else:
            lines.append("- no read (token unknown to on-chain index)")
    return "\n".join(lines) + "\n"


async def main() -> None:
    client = CoinGeckoClient()
    rows: list[Row] = []
    for i, c in enumerate(CANDIDATES):
        if i:
            await asyncio.sleep(2.5)  # GeckoTerminal free tier ~30 req/min
        rows.append(await _assess(client, c))

    # Public-safe stdout summary.
    print("\nInformation-MEV gallery — live run\n")
    print(f"{'Token':<28} {'Venue':<16} {'Liq/Mcap':>10}  Verdict")
    print("-" * 78)
    for r in rows:
        print(
            f"{r.candidate.name:<28} {r.candidate.venue_rating:<16} {_pct(r.ratio_pct):>10}  {_label(r)}"
        )
    caught = sum(1 for r in rows if r.imev and r.imev.label == "manipulated")
    clean = sum(1 for r in rows if r.imev and r.imev.label == "clean")
    print("-" * 78)
    print(f"\n{caught} flagged manipulated · {clean} clean controls · {len(rows)} total\n")

    # Full gallery -> private/ (gitignored).
    out = Path("private/strategy/2026-06-14-information-mev-gallery.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render_gallery(rows))
    print(f"Full gallery written to {out}")


if __name__ == "__main__":
    asyncio.run(main())
