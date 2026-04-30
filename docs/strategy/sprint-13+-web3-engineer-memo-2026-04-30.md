# Sprint 13+ — web3-engineer memo

**Date:** 2026-04-30
**Lens:** x402, Solana, Base/CDP, Cloudflare, frames.ag, on-chain settlement.
**Lane invariant:** the payment settles correctly, idempotently, with verbatim error surfacing.

---

## Theme 1 — Lifecycle monetization (`gecko_pulse`)

1. **Sequencing:** Sprint 14+. Payments-side, this is "more SKUs at existing price points routed through the same `PaymentGate`." Nothing new in my lane until recurrence raises new questions (replay, idempotency across `pulse` calls keyed off the same `idea_id`).
2. **Smallest wedge:** add a `surface: Literal["research","plan","pulse"]` field to `PaymentIntent` so receipts can be filtered per-surface in `bb economics`. Zero new client code.
3. **Risks:** if `pulse` ships as a recurring auto-charge, we accidentally invent subscriptions. My constraint: no facilitator-side recurrence — every pulse is a fresh intent with a fresh `intent_id`.
4. **Cross-lane:** `data-engineer` extends `payment_intents.surface`; `business-manager` confirms per-call pricing.

## Theme 2 — Paragraph creator connector (fan-out)

1. **Sequencing:** Sprint 14. Listing in Bazaar (S12) must settle cleanly first, otherwise a fan-out bug masks as a Bazaar failure.
2. **Smallest wedge:** **single-leg, post-hoc settlement.** User pays Gecko (existing flow). On successful research, *if* a Paragraph source was cited, Gecko fires a separate `creator_payout` intent from the Gecko treasury to the creator. Two transactions, two receipts, both stored against the same `session_id`. Reconciliation = SQL join, not on-chain atomicity.
3. **Architecture call:** **wrapper, not new primitive.** The `X402Client` interface stays single-leg. Add a `PaymentRouter` in `packages/gecko-core/src/gecko_core/payments/` that orchestrates multiple `charge()` calls, persists each leg to `payment_intents` with a `parent_intent_id`, and exposes `settle_with_fanout(legs: list[PaymentLeg])`. The router owns leg ordering, partial-failure semantics ("user-leg success + creator-leg failure → log to `creator_settlements` as `pending`, retry async"), and dashboard accounting. **One tx vs. multiple: multiple.** x402 doesn't atomically multi-route on Solana; pretending it does will burn us when leg-2 fails after leg-1 confirms.
4. **Risks in my lane:**
   - Leg-2 failure after leg-1 confirms → user paid, creator didn't. Mitigation: queued retry + on-chain idempotency keyed off `(session_id, creator_wallet)`.
   - Wallet discovery: creators expose wallets via Paragraph profile? Or do we settle to Paragraph and trust their pass-through? Probe in Sprint 13 spike (4 hr, free).
   - Fan-out math: if creator-leg cost > user payment, we lose money. Pricing floor enforced router-side.
5. **Cross-lane:** `data-engineer` adds `creator_settlements` + `parent_intent_id` (already on V2/V3 roadmap per CLAUDE.md); `software-engineer` wires `PaymentRouter` into the research pipeline post-citation-resolution.

## Theme 3 — Cloudflare x402 (third facilitator)

1. **Sequencing:** Sprint 15. Don't wire a third facilitator until S12 (CDP) is in production and the abstraction has been *tested* by the second facilitator. The abstraction we ship now should be **shaped by 2, validated by 3**.
2. **Smallest wedge:** **as a consumer first, not a contributor.** Add a `CloudflareX402Client` that pays *outbound* for a CF-gated source URL during ingestion. We're a buyer, not a seller-on-CF. Defer CF Workers migration of `gecko-api` to V3 — FastAPI → Workers is a multi-sprint port and the upside (edge billing) doesn't beat CDP for our payer volume.
3. **Architecture call:** **three classes, one Protocol, network-keyed factory.** Not strategy injection. Each facilitator has different auth (frames.ag bearer token from `~/.agentwallet/config.json`; CDP API-key + JWT; Cloudflare API token), different error shapes, and different confirmation models. A single client with strategies smears those differences and re-introduces the catch-and-rephrase anti-pattern. The factory in `packages/gecko-core/src/gecko_core/payments/__init__.py` resolves on `(network, mode)` → client. `X402_NETWORK` picks; `X402_MODE` overrides for stub/dev. **The Protocol stays narrow:** `charge(intent) -> PaymentResult`. Anything facilitator-specific (CF zone IDs, CDP product IDs) lives on the intent extras dict, ignored by clients that don't care.
4. **Risks:** facilitator-neutrality regression — a CDP-only field leaks into the Solana path because the factory was sloppy. Mitigation: `assert intent.network in client.supported_networks` at top of every `charge()`.
5. **Cross-lane:** none new; `software-engineer` keeps the gate thin.

## Theme 4 — App-launching template + marketplace cut

1. **Sequencing:** Sprint 16+. This is a separate product. Don't slip it into a payments sprint.
2. **Smallest wedge:** **scaffold-only, no SDK.** `gecko launch app` generates: (a) a frames.ag wallet bootstrap script (calls their connect API; user pastes OTP); (b) a copy of `gecko_core.payments.gate` *vendored* into the generated repo as `payments/gate.py`; (c) a `bazaar_extension.json` ready to register. **No `gecko-launcher-sdk` package.** Reasons: a runtime SDK couples every launched app's deploy cadence to ours; vendoring is the frames.ag-style distribution we already endorse (skill.md → bootstrap → use). The template is just code-gen + docs.
3. **Marketplace cut — pick:** **(c) honor-system + dashboard-tracked, with (a) optional opt-in.** Argument: (a) Gecko-controlled relayer makes us a money-transmitter under most jurisdictions and breaks wallet neutrality; (b) protocol split doesn't exist in x402 v2 and we don't lead the spec. (c) is the only path that matches our "no subscription, no custody" thesis. Implementation: launched apps emit a settle webhook to Gecko's `/registrar/receipts`; Gecko computes the 1-2% accrual; settlement runs as the V2 `creator_settlements` job (already on roadmap) but in reverse direction. Apps that *opt in* to (a) get a "Gecko-relayed" trust badge on their Bazaar listing — that's the carrot.
4. **Risks:** under-reporting (apps don't fire the webhook). Mitigation: cross-check via Bazaar's discovery API receipt counts where listings are Gecko-registered. Dashboard names-and-shames non-reporters.
5. **Cross-lane:** `staff-engineer` for ToS posture on (c); `business-manager` for the 1% vs 2% number; `software-engineer` owns the scaffold CLI.

---

## Sprint 13 ticket — S13-PAY-01: Facilitator Protocol pre-pay + CDP/CF abstraction seam

**Owner:** web3-engineer
**Cost:** 4 days
**Depends on:** S12-CDP-01..03 landed (or in-flight on a feature branch).

**Why this seam, not just CDP:** S12 ships *one* second facilitator. The risk is hard-coding `if network == base: cdp else: frames` branching that a third facilitator (Cloudflare) reopens 8 weeks later. Pre-paying the seam now costs ~1 day extra over S12's straight CDP wire and saves a 3-class refactor at Theme-3 integration time.

**Scope:**
1. In `packages/gecko-core/src/gecko_core/payments/x402_client.py`, formalize the `X402Client` Protocol with two added members: `supported_networks: frozenset[NetworkName]` (class attr) and `facilitator_id: Literal["frames-solana","cdp-base","cloudflare-http","stub"]`.
2. Move the factory out of `get_client(mode)` into a new `packages/gecko-core/src/gecko_core/payments/factory.py::resolve_client(intent: PaymentIntent) -> X402Client` that keys on `(intent.network, settings.mode)`. Old `get_client(mode)` stays for back-compat, delegates to the new resolver with a synthesized intent.
3. Extend `NetworkName` literal to include `"base-mainnet"` and `"base-sepolia"` (feeds S12 directly) and reserve `"http-cloudflare"` (registered, not implemented; resolver raises `NotImplementedError` with a clear "Sprint 15" message — no stub-fake).
4. Add `PaymentIntent.facilitator_hint: str | None` extras-dict field for forward-compat with CF zone IDs and CDP product IDs without bloating the core model.
5. `bb doctor` reports per-configured-network: `(network → facilitator_id → reachable? balance?)`. Replaces today's single-line "payments: live" output.
6. `CDPX402Client` (skeleton from S12) adopts the Protocol surface; `LiveX402Client` adopts it; `StubX402Client` adopts it and gains a `supported_networks={"solana-devnet","solana-mainnet","base-mainnet","base-sepolia"}` so stub mode works for any network the factory might resolve.

**Acceptance:**
- [ ] `pytest packages/gecko-core/tests/payments/` green, including a new test matrix that asserts every (network, mode) tuple resolves to the right client class.
- [ ] `X402_NETWORK=base-mainnet X402_MODE=stub bb research --idea "smoke"` returns a stub success (proves the factory wires without Solana keys present).
- [ ] `X402_NETWORK=http-cloudflare bb research ...` raises `NotImplementedError` with text mentioning "Sprint 15", **not** a generic KeyError.
- [ ] `bb doctor` output snapshot updated; lists every configured network and its facilitator.
- [ ] No regression in S12 mainnet smoke (re-run S12-LIST-01 against the refactored client; transcript archived).
- [ ] Zero changes to `PaymentResult` shape — gate-side code untouched.

**Out of scope:** Cloudflare client implementation, fan-out router (Theme 2), launcher scaffold (Theme 4), recurrence semantics (Theme 1).

**Files touched:**
- `packages/gecko-core/src/gecko_core/payments/x402_client.py` (Protocol extension)
- `packages/gecko-core/src/gecko_core/payments/factory.py` (new)
- `packages/gecko-core/src/gecko_core/payments/networks.py` (Base + CF entries)
- `packages/gecko-core/src/gecko_core/payments/cdp.py` (Protocol adoption — already present per S12)
- `packages/gecko-core/src/gecko_core/payments/models.py` (`facilitator_hint`)
- `apps/cli/.../doctor.py` (per-network reporting)

Word count target met. Memo ends here.
