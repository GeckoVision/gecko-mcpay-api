"""Hosted-agent runtime surface for gecko-core.

Read-only access to the agent_state Mongo mirror that the hosted paper agent
writes (see contest_bot/agent_store.py's AgentStateStore / MongoBotStateStore).
gecko-core MUST NOT import contest_bot — the Mongo connection pattern is
reimplemented here.
"""
