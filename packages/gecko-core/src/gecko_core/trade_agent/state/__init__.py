"""State persistence for trade-agent runtime.

Three surfaces:

* :mod:`.models` — Pydantic records mirroring the Mongo collections.
* :mod:`.mongo` — async writer protocol + Motor implementation.

The runtime depends on the *protocol*, not the Motor implementation; tests
inject an in-memory stub that mimics the writer interface.
"""

from gecko_core.trade_agent.state.models import (
    AgentJournalEntry,
    AgentMode,
    AgentPosition,
    AgentState,
    AgentStatus,
    AgentVerdictCacheEntry,
    PositionStatus,
)
from gecko_core.trade_agent.state.mongo import (
    InMemoryStateStore,
    MongoStateStore,
    StateStore,
)

__all__ = [
    "AgentJournalEntry",
    "AgentMode",
    "AgentPosition",
    "AgentState",
    "AgentStatus",
    "AgentVerdictCacheEntry",
    "InMemoryStateStore",
    "MongoStateStore",
    "PositionStatus",
    "StateStore",
]
