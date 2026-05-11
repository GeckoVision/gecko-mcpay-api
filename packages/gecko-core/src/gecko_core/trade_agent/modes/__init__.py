"""Mode evaluators — advisor vs trader.

The runtime dispatches by ``AgentSpec``-derived mode. v0.1 ships
advisor; trader is a stub that raises with a clear pointer to AIML-2.
"""

from gecko_core.trade_agent.modes.advisor import AdvisorMode
from gecko_core.trade_agent.modes.trader import TraderMode

__all__ = ["AdvisorMode", "TraderMode"]
