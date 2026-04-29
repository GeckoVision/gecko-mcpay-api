"""gecko_route — cost-aware LLM routing surface (S3-05).

Public entry point: ``route(prompt, task_hint, max_cost_usd, prefer_premium)``.

Picks a model from the routing matrix, charges the caller's x402 wallet,
calls the chosen model via the existing OpenAI-compatible transport
(`gecko_core.orchestration.pro.router`), and returns a `RouteResult` with
cost + savings observability.

Design notes:
- Matrix lives in ``matrix.py`` as data, not branches — pricing changes
  without code changes.
- Prices live in ``costs.py`` (per-model $/M input + $/M output).
- We never silently truncate. Over-budget on the cheapest model is an error.
- x402 charge happens BEFORE the LLM call so a crash mid-call still leaves a
  paid intent (the Pro tier follows the same persist-before-work rule).
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from gecko_core.payments.x402_client import get_client, new_intent_id
from gecko_core.routing.costs import estimate_cost_usd, estimate_tokens, price_for
from gecko_core.routing.matrix import (
    DEFAULT_TASK_HINT,
    TaskHint,
    candidate_models,
    pick_model,
)
from gecko_core.routing.models import RouteResult

if TYPE_CHECKING:
    from gecko_core.payments.models import PaymentIntent

logger = logging.getLogger(__name__)


class RouteBudgetError(Exception):
    """Raised when even the cheapest candidate model exceeds ``max_cost_usd``."""


class RoutePaymentError(Exception):
    """Raised when the x402 charge for a routed call fails. No retry."""


def _build_intent(amount_usd: Decimal) -> PaymentIntent:
    """Construct a stub-friendly PaymentIntent for a routed call.

    The Pro debate uses a real session UUID. Routed calls are session-less
    by design (one-shot), so we mint a fresh UUID4 per call as the
    session_id. Tier is "basic" — gecko_route does not use the Pro debate
    machinery.
    """
    from gecko_core.payments.models import PaymentIntent

    return PaymentIntent(
        intent_id=new_intent_id(),
        session_id=uuid.uuid4(),
        tier="basic",
        amount_usd=amount_usd,
    )


def _select_model(
    *,
    task_hint: TaskHint,
    prefer_premium: bool,
    estimated_in: int,
    estimated_out: int,
    max_cost_usd: float,
) -> tuple[str, float]:
    """Return (chosen_model, estimated_cost_usd) honoring the budget cap.

    Walks the candidate list cheapest-first when the preferred choice would
    exceed ``max_cost_usd``. Raises ``RouteBudgetError`` if no candidate fits.
    """
    candidates = candidate_models(task_hint=task_hint, prefer_premium=prefer_premium)
    # First pass: try the preferred choice.
    preferred = candidates[0]
    pref_cost = estimate_cost_usd(preferred, tokens_in=estimated_in, tokens_out=estimated_out)
    if pref_cost <= max_cost_usd:
        return preferred, pref_cost

    # Downshift: find the cheapest candidate that fits the budget.
    by_cost = sorted(
        (
            (m, estimate_cost_usd(m, tokens_in=estimated_in, tokens_out=estimated_out))
            for m in candidates
        ),
        key=lambda kv: kv[1],
    )
    for model, cost in by_cost:
        if cost <= max_cost_usd:
            return model, cost
    cheapest_model, cheapest_cost = by_cost[0]
    raise RouteBudgetError(
        f"all candidates exceed max_cost_usd={max_cost_usd}: "
        f"cheapest is {cheapest_model} at ${cheapest_cost:.4f}"
    )


def _premium_equivalent(task_hint: TaskHint) -> str:
    """The premium-tier model for a given task_hint, used for savings calc."""
    return pick_model(task_hint=task_hint, prefer_premium=True)


async def _call_model(*, model: str, prompt: str) -> tuple[str, int, int]:
    """Call the chosen model via the existing OpenAI-compatible client.

    Returns (response_text, tokens_in, tokens_out). We reuse the AG2 router
    config so this honors LLM_ROUTER (openai | openrouter | clawrouter) the
    same way the Pro debate does.
    """
    # Lazy import — avoid pulling the OpenAI SDK into modules that just want
    # routing decisions (matrix tests, CLI argument parsing).
    from openai import AsyncOpenAI

    from gecko_core.orchestration.pro.router import resolve_router

    cfg = resolve_router()
    client = AsyncOpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_headers=cfg.extra_headers or None,
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    usage = getattr(resp, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
    return text, tokens_in, tokens_out


def _emit_demo_log(result: RouteResult, task_hint: TaskHint) -> None:
    """One-line demo log on stdout when invoked from the CLI.

    Gated on ``GECKO_ROUTE_LOG=1`` (the CLI sets this). Importing modules
    pay nothing for this — the env check is cheap.
    """
    if os.environ.get("GECKO_ROUTE_LOG") != "1":
        return
    premium = _premium_equivalent(task_hint)
    line = (
        f"[gecko_route] task={task_hint} -> {result.model_used} - "
        f"${result.cost_usd:.4f} (saved ${result.savings_vs_premium:.4f} vs {premium})"
    )
    print(line, file=sys.stdout, flush=True)


async def route(
    prompt: str,
    task_hint: TaskHint = DEFAULT_TASK_HINT,
    max_cost_usd: float = 0.05,
    prefer_premium: bool = False,
) -> RouteResult:
    """Route an LLM call through Gecko's cost-aware router.

    Args:
        prompt: The user prompt. Token-counted to bound spend before calling.
        task_hint: Bias the matrix toward a model class.
        max_cost_usd: Per-call hard cap. Downshifts; raises if even the
            cheapest fit exceeds the cap.
        prefer_premium: If True, take the premium column of the matrix as
            the preferred choice.

    Raises:
        RouteBudgetError: ``max_cost_usd`` cannot be honored by any candidate.
        RoutePaymentError: x402 charge failed (no retry — fail loudly).
    """
    estimated_in = estimate_tokens(prompt)
    # Conservative output estimate: cap at 1024 tokens unless the prompt
    # itself is enormous; matches the typical Pro-debate per-turn ceiling.
    estimated_out = min(1024, max(256, estimated_in // 2))

    chosen, estimated_cost = _select_model(
        task_hint=task_hint,
        prefer_premium=prefer_premium,
        estimated_in=estimated_in,
        estimated_out=estimated_out,
        max_cost_usd=max_cost_usd,
    )

    # Charge before the model call. The Pro tier follows the same rule —
    # persist-before-work means a crash mid-LLM-call doesn't lose the intent.
    intent = _build_intent(Decimal(str(round(estimated_cost, 6))))
    client = get_client()
    payment = await client.charge(intent)
    if payment.status != "success":
        raise RoutePaymentError(
            f"x402 charge failed for intent {intent.intent_id}: {payment.error or 'unknown'}"
        )

    text, tokens_in, tokens_out = await _call_model(model=chosen, prompt=prompt)

    # Recompute actual cost from real token usage (estimate was for budget
    # gating; the cost surfaced to the caller should be the real one).
    actual_cost = estimate_cost_usd(chosen, tokens_in=tokens_in, tokens_out=tokens_out)
    premium = _premium_equivalent(task_hint)
    premium_cost = estimate_cost_usd(premium, tokens_in=tokens_in, tokens_out=tokens_out)
    savings = max(0.0, premium_cost - actual_cost)

    result = RouteResult(
        response=text,
        model_used=chosen,
        cost_usd=actual_cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        savings_vs_premium=savings,
    )
    _emit_demo_log(result, task_hint)
    return result


__all__ = [
    "RouteBudgetError",
    "RoutePaymentError",
    "RouteResult",
    "TaskHint",
    "candidate_models",
    "estimate_cost_usd",
    "estimate_tokens",
    "pick_model",
    "price_for",
    "route",
]
