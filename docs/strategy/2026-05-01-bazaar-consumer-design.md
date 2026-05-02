# Bazaar-Consumer Design Memo (software-engineer lens)

**Date:** 2026-05-01
**Companion to:** staff-engineer plan (in parallel)
**Scope:** how Gecko *consumes* x402 services from CDP Bazaar during ingestion (TripAdvisor, premium arxiv mirrors, etc.)

## 1. One-paragraph design

A `BazaarSourceProvider` is a **new concrete `Source` implementation** that internally composes a new, separate `X402Consumer` Protocol — not a wrapper around existing Sources, and not an extension of `X402Client`. Defense:
1. The existing `Source` Protocol (`gecko_core/sources/__init__.py`) is already the right seam — `applies_to` + `fetch(idea, categories) -> SourceResult` describes any data provider, paid or free; making it a `Source` keeps the dispatcher, catalog, and `SourceResult.cost_usd` rollup uniform.
2. `X402Client` is *seller-side* (`charge(intent) -> PaymentResult`, `verify(tx)`) — its vocabulary is "I am being paid." Consumer-side is `pay_and_fetch(resource_url, max_price)` — semantically inverse, with 402-challenge handling and a budget cap. Forcing both sides through one Protocol would muddy both.
3. Composition (not inheritance) means TripAdvisor, premium arxiv, and a generic Bazaar resource all share one `X402Consumer` while their `Source` bodies stay focused on payload shaping.

## 2. Skeletal interface

```python
# packages/gecko-core/src/gecko_core/payments/consumer.py
@runtime_checkable
class X402Consumer(Protocol):
    """Outbound x402 — Gecko paying a Bazaar endpoint to fetch data."""
    mode: ConsumerMode  # "stub" | "live" | "cdp"
    max_per_call_usd: Decimal

    async def pay_and_fetch(
        self, *, resource_url: str, params: dict[str, Any], budget_usd: Decimal
    ) -> ConsumerResponse: ...  # raises BudgetExceeded, FacilitatorError

    async def discover(self, *, query: str) -> list[BazaarListing]: ...
    # hits /.well-known/x402 catalog on Bazaar; cached.

# packages/gecko-core/src/gecko_core/sources/bazaar.py
class BazaarSourceProvider:
    """Generic — wraps any Bazaar listing as a Source."""
    name: str  # e.g. "bazaar:tripadvisor.places"
    def __init__(self, listing: BazaarListing, consumer: X402Consumer): ...
    async def applies_to(self, *, categories: set[str]) -> bool:
        return bool(self._listing.categories & categories)
    async def fetch(self, *, idea: str, categories: set[str]) -> SourceResult:
        try:
            r = await self._consumer.pay_and_fetch(
                resource_url=self._listing.url,
                params={"q": idea}, budget_usd=self._listing.max_price)
            return SourceResult(self.name, payload=r.body, cost_usd=float(r.paid_usd))
        except BudgetExceeded as e:
            return SourceResult(self.name, fired=False, error=str(e))

# packages/gecko-core/src/gecko_core/sources/tripadvisor.py
class TripAdvisorProvider(BazaarSourceProvider):
    """Thin sub-class only to register a stable catalog entry + categories."""
    name = "tripadvisor"
    # registers via register_source(...) at import time
```

Wiring: `_catalog.py` imports `bazaar` + `tripadvisor` for side-effect registration. `dispatch_sources(...)` already accepts a `list[Source]`, so no dispatcher change. Construction lives in the same factory that builds non-paid providers; it reads `X402_CONSUMER_MODE` and hands every Bazaar provider one shared `X402Consumer`.

## 3. Mode plumbing

**Introduce `X402_CONSUMER_MODE` (separate from existing `X402_MODE`).** Tradeoff: one extra env var, but the seller and buyer roles fail independently — stub-buyer + live-seller is a real dev configuration (don't burn USDC fetching while iterating on receive flows), and a single var would force lockstep. The two modes are defaulted together in dev but resolved independently.

## 4. Test strategy (Pattern C applied to consumer)

Three layers, mirroring the seller-side `live_cdp` pattern:
1. **Stub conformer test.** `StubX402Consumer` returns canned fixtures. Every `BazaarSourceProvider` runs against it in CI.
2. **Recorded-fixture contract test (VCR).** A `live_bazaar` marker (off by default) records once against the real TripAdvisor x402 endpoint via CDP facilitator — captures the 402 challenge, the payment payload shape, and the post-payment 200. Replay in CI with `vcrpy`. Adding a new Bazaar listing is gated on a passing recorded-cassette test, exactly like `live_cdp` for sellers.
3. **Discovery stub.** `/.well-known/x402` responses on Bazaar are stubbed via a fixture file (`tests/sources/fixtures/bazaar_catalog.json`); a separate live-only test refreshes the fixture quarterly. Avoids Pattern C's failure mode (tests that exercise the stub branch only) by routing the `pay_and_fetch` dispatch through the same code path in stub and live — only the HTTP transport is swapped.

## 5. Open questions for staff-eng

- **Budget governance.** Per-session cap, per-source cap, or both? Affects whether `X402Consumer` owns budget or the orchestrator does. Leans orchestrator (sessions already track cost_usd) but it spreads the policy.
- **Provenance shape.** A paid TripAdvisor row in `sources` table needs the tx signature persisted for audit. New column on `sources`, or extend `SourceResult.payload` and rely on JSON? Data-engineer call.
- **Catalog volatility.** Bazaar listings change underneath us. Should `BazaarSourceProvider` instances be constructed at startup (static catalog) or on-demand per session (dynamic discovery)? Dynamic is safer but explodes the `_catalog.py` model that assumes import-time registration.

## Relevant paths

- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/sources/__init__.py` — `Source` Protocol, `SourceResult`, `dispatch_sources`, `register_source`
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/sources/_catalog.py` — import-time catalog wiring
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/payments/protocol.py` — seller-side `X402Client` Protocol (do not extend)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/payments/x402_client.py` — Stub/Live/Frames seller clients (template for consumer-side stub/live/cdp)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/payments/modes.py` — canonical `PaymentMode` Literal (model `ConsumerMode` the same way)

No existing Bazaar/discovery code in repo (grep confirmed).
