# Paysh ingest prep — 2026-05-11

**Owner:** data-engineer (drafted in auto mode, founder-execute gated).
**Status:** **no-go on a $25 / 50-protocol load as framed.** Recommend smaller-scope alternative below.
**Read first:** `project_2026_05_09_session_endstate.md`, this file.

## TL;DR

There is no "50+ protocols" worth of paysh ingest to run. The live paysh catalog at `https://pay.sh/api/catalog` carries **72 providers total**, and the Solana-DeFi planner filter selects **exactly 3** of them. The "broken URLs" complaint resolves to two known providers whose catalog `service_url` is already rewritten by `service_call_specs.py` url_overrides — they are not broken, they are quirks already handled. Every URL in the catalog HEAD-checks alive (zero DNS / connection / TLS failures across all 72). A `$25` cap against `--protocols Jupiter,Kamino,Pyth,Drift,Jito` is structurally impossible to spend: 5 protocols × 3 listings × $0.01 typical settle = **~$0.15 per full sweep**.

Recommendation: re-run the existing **$5 cap** against the canonical 5 protocols. Decide whether to expand the planner filter (small code change in `prompt.py`) or expand the protocol list (CLI flag) to grow coverage. Do **not** flip the cap to $25 without a wider filter — money will not move.

## 1. Broken URLs found

10-URL stratified sample then full 72-URL HEAD survey. All targets answered; categorized below.

| URL category | Count | Examples | Suspected cause |
|---|---:|---|---|
| `200 OK` on `HEAD /` | 19 | stablecrypto.dev, dtelecom.org, x402.dtelecom.org | x402 host that serves a landing page on `/` |
| `4xx` on `HEAD /` (alive but no resource at root) | 53 | x402.api.agentmail.to, *.alibaba.gateway-402.com | Normal x402 behavior — paid path is a subpath, root 404s |
| `5xx` / `3xx` / DNS / TLS / timeout / refused | 0 | — | None. Catalog topology is clean. |

Full results captured to `/tmp/paysh_head_results.json` (read-only diagnostic, not committed).

### "Broken" URLs the planner actually targets

After the Solana-DeFi filter, the planner reduces 72 → 3:

| fqn | catalog service_url | What runner actually hits | End-to-end probe |
|---|---|---|---|
| `merit-systems/stablecrypto/market-data` | `https://stablecrypto.dev` | `https://stablecrypto.dev?q=<prompt>` (legacy GET-with-?q=) | **200 OK with HTML body** — NOT a 402 challenge. Runner aborts with `"expected 402 challenge from … got 200"`. This is the genuine bug. |
| `paysponge/coingecko` | `https://pro-api.coingecko.com/api/v3/x402/onchain` | `pro-api.coingecko.com/api/v3/x402/onchain/search/pools?query=…&network=solana` (rewritten by `_coingecko_url_override`) | **402 with `payment-required` header** — works. |
| `paysponge/perplexity` | `https://pplx.x402.paysponge.com` (302s to dashboard HTML) | `https://pplx.x402.paysponge.com/v1/sonar` (rewritten by `_perplexity_url_override`) | **404** with body `"Endpoint not found. … Only registered endpoints can be called."` — the override path no longer matches paysponge's current Perplexity endpoint. |

So the real broken-URL set, by category:

| URL | Status | Category | Cause |
|---|---|---|---|
| `stablecrypto.dev?q=…` | 200 HTML | non-402 endpoint | Not an x402 endpoint — root is the marketing site. No `service_call_specs.py` spec routes us to its actual paid path (if one exists). |
| `pplx.x402.paysponge.com/v1/sonar` | 404 | stale path override | The override pinned 2026-05-08 has rotted. Paysponge changed the Perplexity path; need to probe / contact for current path. |

## 2. Root cause analysis

Two layers conflate as "broken URLs":

1. **Catalog topology is fine.** `service_url` for every one of the 72 providers resolves over DNS, completes TLS, and answers HTTP. Nothing in `paysh_manifest.py` URL construction is wrong; the SSRF guard, schema validation, and fetcher all work. The `fetch_catalog` change in `494987e` (exposing `providers[]` on the payload) restored the runner's view of the catalog correctly.
2. **The runner's contract with x402 sellers is brittle.** The runner expects a `402` challenge on `GET service_url?q=…`. That is the "legacy paysh REST" assumption baked into `_LiveX402PaidRequester.request` (line ~683-714 of `scripts/trading_oracle/run.py`). Two of the 3 selected listings (`coingecko`, `perplexity`) already required per-service `url_override` to find their actual paid path. The third (`stablecrypto`) has no override and its catalog `service_url` is its marketing root — not an x402 endpoint. The perplexity override has bit-rotted (was confirmed 2026-05-08; today returns 404).

This is the same Pattern B shape called out in `CLAUDE.md`: "first deliverable is a free local simulation script… Live smoke is the final verification." Today we have neither a contract test for paysh providers nor a probe-before-spend pre-flight, so URL drift surfaces only when we pay.

## 3. Draft fix (NOT committed)

Two surgical changes, neither riskier than the runner already is. Both add log-and-skip behavior; neither changes the spend path. Apply both before re-running.

### 3a. Pre-flight URL probe in `scripts/trading_oracle/run.py`

Probe each planned call once with a free `GET` (no payment header). Skip listings whose probe does NOT return `402` — they cannot be paid, so issuing the paid retry is dead money. Log every skip with the observed status code.

```diff
--- a/scripts/trading_oracle/run.py
+++ b/scripts/trading_oracle/run.py
@@ -946,6 +946,55 @@ def _build_evm_requester_for_fallback(*, advertised: list[str]) -> Any:
     )
 
 
+async def _preflight_probe(call: "PlannedCall") -> tuple[bool, str]:
+    """Free GET probe — return (ok, reason) without spending.
+
+    Skip-before-spend safety net. A paid listing MUST answer the
+    unauthenticated probe with 402; anything else (200 HTML marketing
+    site, 404 stale path, 5xx) means the catalog URL is not a live x402
+    endpoint right now. We bail out of the paid retry in that case so
+    the run doesn't burn settlement-side gas on a guaranteed failure.
+
+    Returns ``(True, "402 ok")`` on success or ``(False, reason)``.
+    Network errors are reported as ``(False, "probe error: …")`` and
+    treated as skip rather than fatal — a one-off blip should not stop
+    the rest of the matrix.
+    """
+    import httpx
+    from urllib.parse import urlparse
+
+    service_url = str(call.listing.get("service_url", ""))
+    if not service_url:
+        return False, "empty service_url"
+
+    # Apply the same url_override path the live requester uses, so we
+    # probe the URL we'd actually pay against (not the catalog stub).
+    try:
+        from service_call_specs import find_spec_for  # type: ignore[import-not-found]
+        eps = call.listing.get("endpoints") or [{"url": service_url, "method": "GET"}]
+        spec, _ep = find_spec_for(
+            call.listing.get("fqn") or urlparse(service_url).hostname or "",
+            list(eps),
+        )
+        probe_url = (
+            spec.url_override(_CURRENT_QUERY or "", {})
+            if spec is not None and spec.url_override is not None
+            else service_url
+        )
+    except Exception as exc:  # noqa: BLE001
+        return False, f"probe registry lookup failed: {exc}"
+
+    try:
+        async with httpx.AsyncClient(timeout=6.0) as client:
+            resp = await client.get(probe_url, params={"q": "ping"})
+    except httpx.HTTPError as exc:
+        return False, f"probe error: {type(exc).__name__}: {exc}"
+    if resp.status_code == 402:
+        return True, "402 ok"
+    return False, f"probe returned {resp.status_code} (expected 402)"
+
+
 async def _charge_and_fetch(call: PlannedCall) -> dict[str, Any]:
```

Then gate the dispatcher on the probe inside the `for protocol in protocol_list:` loop just before `execute_plan`:

```diff
@@ -1252,6 +1301,18 @@ def main(
             if dry_run:
                 log.info("DRY RUN [%s] — no charges, no writes.", protocol)
                 continue
 
+            # Pre-flight: drop any planned call whose URL does not 402.
+            kept: list[PlannedCall] = []
+            for c in plan.calls:
+                ok, reason = await _preflight_probe(c)
+                if ok:
+                    kept.append(c)
+                else:
+                    log.warning("[%s] PROBE-SKIP %s reason=%s", protocol, c.name, reason)
+            plan = type(plan)(calls=kept, skipped=plan.skipped,
+                              projected_total_usd=sum((c.price_usd for c in kept), Decimal("0")))
+
             # Bind the per-protocol query for this pass. _charge_and_fetch
```

(The `type(plan)(...)` reconstruction assumes `PlanResult` is a dataclass with those three fields — confirm the actual constructor signature in `run_live_ingest.py` before applying, and adjust if it has more fields.)

### 3b. Per-failure logging in `execute_plan` callers (optional, lower priority)

The current `cumulative_failures.extend(...)` only stores the failure string but not the URL that caused it. Tightening this would make tomorrow morning's review one-glance instead of a grep-through-stdout. Not load-bearing; defer if scope is tight.

### What this fix does NOT do

- Does not silently replace stale `url_override`s (paysponge/perplexity needs human triage with paysponge contact, not code).
- Does not widen the Solana-DeFi filter (deliberate; widening without a quality check would burn budget on irrelevant LLM calls).
- Does not retry transient failures with backoff — the runner is already short-lived; if a 402 probe blips, the whole protocol pass picks it up next loop.

## 4. Smoke test result

### 4a. 10-URL HEAD-check sample

Full 72-URL survey actually completed (cheaper than I expected) — results above in section 1. Highlights:

```
alive_2xx       19
alive_4xx       53   (expected for x402 hosts — root is not the paid path)
alive_5xx        0
redirect_3xx     0
dns_fail         0
conn_refused     0
timeout          0
tls_err          0
```

### 4b. 1-good + 1-broken end-to-end probe

| Target | HEAD | GET | Verdict |
|---|---|---|---|
| `https://pro-api.coingecko.com/api/v3/x402/onchain/search/pools?query=kamino&network=solana` (good) | 402 + `payment-required` header | 402 body `{"error":"Payment required",…}` | Paying path is live. |
| `https://pplx.x402.paysponge.com/v1/sonar` (broken — stale override) | 404 | 404 body `"Endpoint not found … only registered endpoints can be called"` | Override has rotted. Probe-skip will catch it. |
| `https://stablecrypto.dev?q=kamino` (broken — marketing root) | 200 HTML | 200 `<!DOCTYPE html>…` | Not an x402 endpoint. Probe-skip will catch it. |

## 5. Large-load plan

**The "huge load" framing does not fit the data.** Concrete numbers:

| Metric | Value | Source |
|---|---|---|
| paysh catalog provider count | 72 | live `/api/catalog` 2026-05-11 |
| Selected by Solana-DeFi filter | 3 | `is_solana_defi_relevant` over current catalog |
| Default protocol count | 5 | `--protocols Jupiter,Kamino,Pyth,Drift,Jito` |
| Max calls per full run (today) | 3 × 5 = 15 | planner runs per-protocol pass |
| Typical settle cost per call | $0.001 – $0.01 | observed across coingecko/perplexity in S22 |
| Expected total spend at default | **~$0.05 – $0.15** | 15 × ~$0.01 |
| Per-call hard cap (`--max-per-call-usd`) | $0.10 default | runner flag |
| Run cap (`--cap-usd`) | hard cap across all protocols, cumulative | `cumulative_spent += report.spent_usd; if remaining <= 0: break` |

**`--cap-usd` is a hard cap, decremented across protocol passes** (verified in `run.py:1226-1234`). The loop exits when remaining ≤ 0 before issuing the next pass. Within a pass, individual call cost is bounded by `--max-per-call-usd` via `_check_advertised_within_limit`.

After the probe-skip patch lands, only `paysponge/coingecko` will survive the probe gate. **1 listing × 5 protocols = 5 calls per run, ≤ $0.05 expected.**

### Recommended caps for the "wake up to a real result" scenario

| Scenario | Cap | Per-call | Protocols | Expected spend | Recommended? |
|---|---|---|---|---|---|
| Today, with patch | $1 | $0.10 | default 5 | ~$0.05 | YES — covers the actual selectable set with a comfortable margin |
| Today, no patch | $5 | $0.10 | default 5 | ~$0.10 if lucky, runner-error on `stablecrypto` and `perplexity` | NO — wastes 2/3 of paid attempts |
| Founder's "huge $25 / 50-protocol" framing | $25 | $0.10 | extended | impossible to spend at the filter's current selectivity | NO — re-scope first (see below) |

### If the founder genuinely wants to spend ~$25 of paysh budget

The blocker is **selection**, not cap. To grow coverage:

- **Option A — widen `--protocols` list.** `prompt_for_protocol` accepts arbitrary names; `is_solana_defi_relevant` does not gate on the protocol list (it filters listings, not protocols). So 50 protocols against 3 listings = still 150 calls × $0.01 = ~$1.50.
- **Option B — widen `is_solana_defi_relevant`.** Add more `_DEFI_TOKENS` / `_SOLANA_TOKENS`, or temporarily disable the filter and let the planner pick across the full 72 providers. Most of the 72 are AI-LLM (Bankr, BlockRun, exa) and would pull in irrelevant content. Needs `ai-ml-engineer` review on retrieval quality before flipping.
- **Option C — pivot to bazaar.** Bazaar catalog has ~5-6x more services and many are already research-LLM-shaped. Different wallet (Base, not Solana). Out of scope for tomorrow.

Recommend: **patch + Option A small (10-15 protocols) + cap $2**. Real result, no surprises.

## 6. Go/no-go checklist for tomorrow morning

Verify in this order:

1. **Read this runbook.** Confirm the "50+ protocols" framing was based on stale memory; the canonical paysh catalog is 72 providers / 3 selected, and a $25 cap is not spendable today.
2. **Decide:**
   - **Path 1 (recommended):** Apply the probe-skip diff above by hand (it is NOT committed). Re-run with `--cap-usd 2 --protocols Jupiter,Kamino,Pyth,Drift,Jito,Raydium,Marinade,Phoenix,Tensor,Orca`. Expected: ~5-10 successful coingecko calls, ~$0.05-$0.10 spent, written to Mongo.
   - **Path 2:** Skip the patch; accept that 2/3 paid attempts per protocol will runner-error. Lower cap to $1. Same recommended protocols.
   - **Path 3:** Defer the run, schedule an `ai-ml-engineer` consult on widening `is_solana_defi_relevant` for a meaningful $25 sweep next week.
3. **Pre-flight env:** `source .env && echo $GECKO_X402_MODE` must print `live`. `echo $GECKO_SOLANA_WALLET_ADDRESS` must be non-empty. (Do not paste the private key. Per security non-negotiables, agents do not read it; you confirm presence.)
4. **Mongo Atlas write path:** Confirm `MONGODB_URI` env is set; one prior successful chunk write in the last 24h is the proof — check via the Atlas UI session log, not a script.
5. **Supabase migration gate:** Verify `20260509000000_provider_kind_marketplace.sql` is applied on the remote project. Per `project_2026_05_09_session_endstate.md` queue item #1 — without it, every paysh ingest fails the `sources` row write with `23514`. If unsure, this is a blocker.
6. **Run the command:**

   ```bash
   uv run python scripts/trading_oracle/run.py \
     --source paysh \
     --cap-usd 2.00 \
     --max-per-call-usd 0.10 \
     --protocols Jupiter,Kamino,Pyth,Drift,Jito,Raydium,Marinade,Phoenix,Tensor,Orca \
     2>&1 | tee /tmp/paysh-ingest-$(date -u +%Y%m%dT%H%M%SZ).log
   ```

7. **Post-run review (5 min):** grep the log for `PROBE-SKIP` (expected for stablecrypto + perplexity), `x402 settled` (expected for coingecko), `FAIL` (should be empty after patch), and final `ALL PROTOCOLS DONE` line. Count Mongo chunks written; verify in Atlas that `protocol` and `vertical=dex` tags are present.
8. **If anything looks wrong** — `Ctrl-C`. The cap is the safety net, but a panicked stop costs nothing extra.

## What I did NOT do (per task constraints)

- No paid API calls. No LLM calls. No Mongo writes. No Supabase writes.
- No git commits. No file writes outside `docs/runbooks/`.
- No `git add`, no branch creation. Working tree is untouched apart from this file.
- The draft diff in section 3a is text only; the founder applies it (or asks data-engineer to follow up after morning review).

## Loose ends for a follow-up session

- Probe paysponge for the current Perplexity endpoint path; update `_perplexity_url_override` accordingly.
- Decide whether `stablecrypto.dev` has a documented x402 path (probe `/api/x402/*`, `/v1/x402`, or contact merit-systems). If not, blocklist its fqn the same way Venice is.
- Schema-drift safeguard: a `tests/test_paysh_overrides_alive.py` that runs the same probe done in section 4b against every `url_override` URL in CI, fails when the path 404s. Pattern A + Pattern C alignment — codify the override registry against live endpoints once, gate further drift on it.
