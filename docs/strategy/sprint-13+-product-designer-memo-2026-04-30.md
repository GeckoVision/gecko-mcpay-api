# Sprint 13+ — product-designer memo

**Date:** 2026-04-30
**Lens:** terminal output, document reveal, receipt anatomy, sub-fold copy.
**Predecessor:** `docs/strategy/bazaar-composer-design-review-2026-04-30.md` (latency budget, vertical-themed spinner, additive sub-fold).

---

## Theme 1 — Lifecycle monetization (`gecko_pulse`)

1. **Sequencing.** UX-readiness gates this to **Sprint 15+**. The reveal pattern in `render.py` (header → BP panel → Rule → VR panel → Rule → PRD panel) is built for first contact, not the second visit. Pulse needs a *delta* renderer before it ships, and we don't have one.
2. **Reveal moment.** Not a notification. Notifications are the wrong cognitive frame — they interrupt; we want the founder to *come back*. Three surfaces, ranked: (a) `bb pulse` returns a single `Panel` titled `WEEK 3 — what changed` with a green/yellow/red verdict on each pillar from last session's PRD; (b) MCP `gecko_pulse` returns the same shape so Claude Code can read it inline; (c) email digest is V3 — out of lane. The reveal must read as *one beat shorter than research*: a single panel, no Rules. Research is three documents; pulse is one verdict + three deltas. The compression itself signals "this is recurring, not ceremonial."
3. **Anti-pattern.** Re-rendering the full three-panel reveal on every pulse. Repetition kills the original reveal's weight. If pulse looks like research, research stops feeling earned.

## Theme 2 — Paragraph creator connector

1. **Sequencing.** **Sprint 13 or 14** — the receipt extension is small and the citation surface already exists (`_citations_renderable`, `render.py:91`).
2. **Reveal moment.** In the citations footer of any panel that consumed Paragraph excerpts. Surface the creator. Hiding them is the Zapier failure mode in reverse: we'd be paying creators while erasing them. Spec:
   ```
   [3] https://paragraph.xyz/@author/post-slug  chunk 4  (sim 0.82)
       @author · 0.0050 USDC paid · sol:7xKX…9Lm
   ```
   Wallet truncated, payment dimmed, handle bold-accent. The line lives in citations, **not** in the spinner (S12 rule: providers in receipts, not progress). The receipt's `Bazaar-routed sources` line gets a sibling: `Creator payouts ......... $0.015` with a `└─ 3 creators (Paragraph)` disclosure.
3. **Anti-pattern.** Putting "$0.005 paid to @author" inline next to each claim in the body. That turns the Validation Report into a tip jar and breaks scanability. Payment is a citation property, not a sentence ornament.

## Theme 3 — App-launching template (`gecko launch`)

1. **Sequencing.** **Sprint 16+.** This is a new flow class, not a new panel. Shipping it before Pulse and Paragraph dilutes the reveal brand.
2. **Reveal moment.** **Single command + generated README, no interactive prompts.** Click prompts feel like a setup wizard; setup wizards feel like Heroku 2014. Spec:
   ```
   bb launch --kind content-api --domain hotels --idea "regional guides"
   ```
   Output is two artifacts side-by-side in the terminal: (a) a `Tree` renderable showing the scaffolded directory (Rich `rich.tree.Tree`), (b) a `Panel` titled `NEXT 5 MINUTES` with exactly five numbered steps. The validation pre-roll runs *before* scaffolding and renders as the standard three-panel reveal — so the launcher inherits the trust beat instead of replacing it. The generated `README.md` mirrors the `NEXT 5 MINUTES` panel verbatim so the terminal and the file say the same thing.
3. **Anti-pattern.** Click `prompt()` chains ("What's your domain? [hotels]: "). Every prompt is a chance to abandon. The first 5 minutes of a scaffolder are won by *one* command and *one* document, not by a conversation.

## Theme 4 — Cloudflare x402 as content-source

1. **Sequencing.** **Sprint 14**, behind Paragraph. Mostly invisible — the source pipeline already abstracts providers.
2. **Reveal moment.** Only visible on failure. Success path: another row in the receipt's Bazaar-routed disclosure. Failure path is the whole UX surface:
   ```
   Couldn't reach a Cloudflare-gated source for "industry-report.example.com".
   The verdict shipped without it. Critic agent flagged: "missing premium signal".
   Detail in ~/.gecko/logs/session-<id>.log
   ```
   The critic-agent flag is the magic move — degradation becomes content (S12 latency principle re-applied). No stack trace. No "x402 facilitator" jargon. The error names a domain the founder recognizes.
3. **Anti-pattern.** A red `ERROR: x402 facilitator unreachable` panel that aborts the session. Facilitator neutrality only holds if Cloudflare's absence is a *paragraph in the validation report*, not a fatal exit.

---

## 4. The dual sub-fold revisited

**Earned: triple, not unified.** Per S12 memo, abstraction earns its keep at *three concrete instances*. With Cloudflare we have it. `landing-copy-v2.md` lines 34–43 (hero sub block) get a third stacked sub-fold:

> **Above frames.ag.** Agents will spend your money. Gecko approves the spec first.
>
> **Above the Bazaar.** Agents discover what to buy. Gecko tells them what to build.
>
> **Above Cloudflare's gate.** Agents can pay any paywall. Gecko decides which paywalls are worth it.

Three concrete rails, same shape. **Don't unify yet.** "Above any x402 facilitator" becomes honest in **Sprint 17**, after a fourth rail (likely `awal` agentic-wallet, per S12 memo §5) ships. The unification line earns its abstraction when the pattern is so obvious the reader completes it before we do. Three is the pattern; four is the proof.

Paragraph is **not** a sub-fold — it's a creator-side surface, not a facilitator. It belongs in the receipt anatomy, not the apex stack.

---

## 5. Sprint 13 ticket — S13-PD-01: Citation creator-attribution

**Effort:** 4 days. **Owner:** product-designer (spec) + software-engineer (build).

**Scope.** Extend `Citation` rendering in `apps/cli/src/gecko_cli/render.py` (`_citations_renderable`, lines 91–107) to surface creator handle, payout amount, and truncated wallet when present. Add disclosure row to receipt block in `landing-copy-v2.md` Card B (Pro, lines 78+) and Card C (Pro+, S12 memo §3).

**Acceptance criteria.**
1. `Citation` model gains optional `creator_handle: str | None`, `creator_wallet: str | None`, `payout_usdc: Decimal | None` (data-engineer dependency for schema).
2. When present, `_citations_renderable` emits a second indented line per citation in the spec'd format (`@handle · NNNN USDC paid · sol:XXXX…XXXX`), dim-styled, wallet truncated to 4+4.
3. When absent, current rendering is byte-identical (snapshot test).
4. Receipt block (`landing-copy-v2.md`) gains `Creator payouts` line with vertical-pipe disclosure, only when N>0 creators paid that session.
5. Width tests pass at 80, 120, 200 columns (no line wrap on the truncated wallet).
6. No emoji. No model names. No facilitator jargon — "Paragraph" is acceptable, "x402 facilitator" is not.
7. Snapshot tests in `apps/cli/tests/test_render.py` cover: zero creators, one creator, three creators, one creator with missing wallet.

**Out of scope.** Payment execution (web3-engineer). Schema migration (data-engineer). The `bb research --show-providers` flag from S12 memo §3 — separate ticket.

---

**Files referenced:**
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/apps/cli/src/gecko_cli/render.py` (lines 91–107, 277–322)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/docs/marketing/landing-copy-v2.md` (lines 34–43, 78+)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/docs/strategy/bazaar-composer-design-review-2026-04-30.md` (§3, §4, §5)
