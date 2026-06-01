"""Sprint 25 (#117, #141): Kamino USDC paper-mode auto-sink.

PAPER ONLY. No on-chain calls in this package. The bot's idle USDC is
simulated as deposited into Kamino's main USDC reserve, accruing the
live supply APY via a cached HTTP fetch. Disabled by default; flipped on
per-launcher via `GECKO_KAMINO_PAPER_SINK=1`.

Public surface (importable as ``from kamino import ...`` when the
contest_bot dir is on sys.path, mirroring the rest of contest_bot):

    apy_cache.KaminoAPYCache
    paper_ledger.PaperLedger
    paper_sink.KaminoPaperSink

See: docs/build-plan-sprint-25-kamino-paper-sink.md
"""

from __future__ import annotations

from kamino.apy_cache import KaminoAPYCache
from kamino.paper_ledger import PaperLedger
from kamino.paper_sink import KaminoPaperSink

__all__ = [
    "KaminoAPYCache",
    "KaminoPaperSink",
    "PaperLedger",
]
