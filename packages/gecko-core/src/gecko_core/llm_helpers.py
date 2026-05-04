"""Cross-cutting LLM-helper functions (LLM-hygiene Commit D).

Currently exposes two related concerns:

- ``pydantic_to_strict_schema`` — adapt a Pydantic model's JSON schema to the
  shape OpenAI's ``response_format={"type":"json_schema","strict":true}``
  Structured Outputs mode requires. The Structured Outputs API rejects the
  defaults Pydantic emits (``additionalProperties: true``, ``$ref`` chains
  into ``$defs``, partially-required object properties). This helper does
  the deterministic post-processing in one place so call sites stay one-line.

- ``supports_strict_outputs`` — predicate the call sites use to decide
  whether to opt into strict mode. We are intentionally conservative:
  return ``True`` only when the active router is OpenAI direct (or the
  legacy plane configured against api.openai.com). Non-OpenAI providers
  via OpenRouter are routed through the ``json_object`` fallback even
  though some technically support strict mode — we expand the predicate
  one provider at a time as we record contract evidence that the
  ``json_schema`` round-trip is stable for them.

- ``build_response_format`` — convenience wrapper that returns the right
  ``response_format`` payload for a given (Pydantic model, model_id, router)
  triple. Most call sites use this directly.

The Pydantic adapters added in commit f67b211 (the ``what_they_do`` /
``acceptance_criteria`` string-vs-list coercers) stay in place: they are
the safety net for the ``json_object`` fallback path, harmless under strict
mode (the model never produces the drifted shape so the coercer never
fires). Don't remove them with this commit.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

# Routers that CAN reach OpenAI's Structured Outputs strict-mode endpoint.
# Conservative on purpose: OpenRouter technically supports strict mode for
# OpenAI-provider routes, but until each non-OpenAI provider has a recorded
# contract test we route everyone else through the json_object fallback
# (the existing Pydantic adapters cover the remaining drift).
_STRICT_OUTPUT_ROUTERS: frozenset[str] = frozenset({"openai", "legacy"})


def supports_strict_outputs(model_id: str, router: str) -> bool:
    """Return True iff the (model, router) pair can run strict json_schema mode.

    Args:
        model_id: The catalog id about to be sent on the wire (e.g.
            ``"openai/gpt-4.1-nano"``, ``"anthropic/claude-sonnet-4.6"``,
            or a bare ``"gpt-4o"`` when scaffold/flywheel pin a literal).
        router: The active router name (``"openai"`` / ``"openrouter"`` /
            ``"clawrouter"`` / ``"legacy"``). When ``cfg.source ==
            "router:<name>"``, this is ``<name>``; ``cfg.source == "legacy"``
            normalises to ``"legacy"``.

    Returns ``True`` only when the router can speak OpenAI's Structured
    Outputs API: today, that's ``openai`` direct and ``legacy`` (which
    points at api.openai.com or a ClawRouter shim that proxies it). All
    other routers fall back to ``{"type": "json_object"}`` so the
    Pydantic-adapter safety net handles non-conforming output.

    Note on router=='clawrouter': ClawRouter proxies to OpenAI in dev,
    but is treated as non-strict here because the cost telemetry header
    plumbing assumes the upstream is the canonical OpenAI shape. Re-
    enable once the clawrouter→openai route has a recorded fixture
    contract for strict mode.
    """
    router_norm = (router or "").strip().lower()
    if router_norm not in _STRICT_OUTPUT_ROUTERS:
        return False
    # Belt-and-suspenders: even on the OpenAI plane, only opt in for OpenAI
    # model ids. A bare model id with no provider prefix (e.g. ``"gpt-4o"``)
    # is OpenAI-shaped and acceptable. ``openai/<id>`` is acceptable. Any
    # other provider prefix indicates a fallback didn't fire and we should
    # not promise strict mode to the wire.
    mid = model_id.strip()
    if "/" not in mid:
        return True
    return mid.startswith("openai/")


def pydantic_to_strict_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Render ``model_cls`` as a JSON schema compatible with OpenAI strict mode.

    The OpenAI ``json_schema`` strict mode imposes four invariants that
    Pydantic's default ``model_json_schema`` doesn't meet out of the box:

    1. Every object node must declare ``additionalProperties: false``.
    2. Every property listed in ``properties`` must also appear in
       ``required`` (Optional/default fields stay nullable via type
       widening, not by being absent from ``required``).
    3. ``$ref`` chains into ``$defs`` are accepted, but each referenced
       definition must itself satisfy invariants 1+2 (Pydantic emits
       child schemas with ``additionalProperties: true`` by default).
    4. The root object cannot use ``oneOf``/``anyOf`` at the top level —
       wrap in a single object first if needed (none of our call sites
       hit this; we don't add a wrapper here).

    Implementation: render the schema, walk every nested ``object`` node
    (root, ``$defs``, nested ``properties``, ``items``, ``anyOf``/``oneOf``
    branches), and rewrite in-place. ``$ref`` is left intact — strict
    mode resolves refs into ``$defs`` natively, which keeps the schema
    compact for nested models like ``Citation`` reused across BusinessPlan
    / ValidationReport / PRD.
    """
    raw = model_cls.model_json_schema()
    # Deep-copy so we never mutate Pydantic's cached schema dict.
    schema = deepcopy(raw)

    # Walk root, every $defs entry, and every nested object recursively.
    _strict_rewrite(schema)
    defs = schema.get("$defs")
    if isinstance(defs, dict):
        for def_value in defs.values():
            if isinstance(def_value, dict):
                _strict_rewrite(def_value)

    return schema


def _strict_rewrite(node: dict[str, Any]) -> None:
    """In-place: enforce strict-mode invariants on a single schema node + descendants.

    Recurses into ``properties.*``, ``items``, and ``anyOf`` / ``oneOf`` /
    ``allOf`` branches so deeply-nested object schemas (Citation lists
    inside BusinessPlan, etc.) all get the same treatment.
    """
    node_type = node.get("type")
    # An object node: enforce additionalProperties=false and required==keys.
    if node_type == "object" or "properties" in node:
        node["additionalProperties"] = False
        props = node.get("properties")
        if isinstance(props, dict):
            # Strict mode: every property in `properties` must be in
            # `required`. Optional fields stay schema-valid because their
            # type already widens to include "null" (Pydantic emits
            # `anyOf: [{type: ...}, {type: "null"}]` for `X | None`).
            node["required"] = list(props.keys())
            for child in props.values():
                if isinstance(child, dict):
                    _strict_rewrite(child)

    # Array node: descend into items.
    items = node.get("items")
    if isinstance(items, dict):
        _strict_rewrite(items)
    elif isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                _strict_rewrite(it)

    # Union branches.
    for combinator in ("anyOf", "oneOf", "allOf"):
        branches = node.get(combinator)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    _strict_rewrite(branch)


def build_response_format(
    model_cls: type[BaseModel] | None,
    model_id: str,
    router: str,
    *,
    name: str | None = None,
) -> dict[str, Any]:
    """Return the ``response_format`` payload for a JSON-emitting call site.

    When ``model_cls`` is provided AND ``(model_id, router)`` supports
    strict mode, returns a ``json_schema`` payload derived from the
    model. Otherwise returns the legacy ``{"type": "json_object"}`` and
    relies on Pydantic ``model_validate`` (with the f67b211 coercers) at
    the call site.

    Pass ``model_cls=None`` to force ``json_object`` (used by sites whose
    output shape is ad-hoc — e.g. the contradictions LLM-judge that just
    needs ``{"contradicts": bool, "reason": str}`` and isn't validated
    through a shared Pydantic class).
    """
    if model_cls is None or not supports_strict_outputs(model_id, router):
        return {"type": "json_object"}
    schema = pydantic_to_strict_schema(model_cls)
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name or model_cls.__name__,
            "schema": schema,
            "strict": True,
        },
    }


__all__ = [
    "build_response_format",
    "pydantic_to_strict_schema",
    "supports_strict_outputs",
]
