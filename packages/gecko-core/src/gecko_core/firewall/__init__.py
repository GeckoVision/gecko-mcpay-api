"""Gecko Decision Firewall — the SendAI-consumer surface + the verdict ledger.

This subpackage holds the two MISSING edges from
``docs/architecture/firewall-e2e.md`` in their thinnest honest form:

  * :mod:`gecko_core.firewall.pretrade` — ``pretrade_check`` + a
    :class:`~gecko_core.firewall.pretrade.FirewallGate` whose ``submit`` mirrors
    the SendAI exec adapter, so it reads as "the gate the SendAI adapter consults
    before executing." It does NOT execute — it consults ``/safety`` and returns
    a proceed decision.
  * :mod:`gecko_core.firewall.ledger` — the ``firewall_verdicts`` row (the moat's
    first row) + ``record_firewall_verdict``: Mongo when configured, else a local
    JSONL dev artifact, same schema.

The firewall *engine* (signals/fusion/monitor/cache) lives under
``gecko_core.trade_agent.hotpath`` and is reused as-is; nothing here re-implements
it. The serve path is ``gecko_api.safety_fast.serve_safety``.
"""

from __future__ import annotations

from gecko_core.firewall.ledger import (
    FIREWALL_VERDICTS_COLLECTION,
    JSONL_FALLBACK_PATH,
    FirewallVerdict,
    record_firewall_verdict,
)
from gecko_core.firewall.pretrade import (
    FirewallGate,
    PretradeDecision,
    pretrade_check,
)

__all__ = [
    "FIREWALL_VERDICTS_COLLECTION",
    "JSONL_FALLBACK_PATH",
    "FirewallGate",
    "FirewallVerdict",
    "PretradeDecision",
    "pretrade_check",
    "record_firewall_verdict",
]
