# S33 — Chunk Production Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `provider_kind` in the trading-oracle corpus emits well-formed parsed prose (no raw JSON blobs), carries provenance + freshness metadata, and is reproducible from tracked code.

**Architecture:** The protocol-native ingest pipeline currently lives only in git worktrees (reproducibility crisis). Phase 0 commits it to tracked code. Phase 1 rewrites the shared `render_chunk()` renderer so kamino/jupiter/jito payloads become per-entity parsed prose instead of pretty-printed JSON, and adds an `as_of_date` field. Phase 2 re-ingests and re-measures against the 6-dim rubric. Sprint S33 is the first of three (S33 chunks → S34 retrieval → S35 lock-green).

**Tech Stack:** Python 3.11 / uv workspace · MongoDB Atlas (chunks) · Voyage embeddings · pytest · ruff · mypy

---

## Scope & ticket reconciliation

| Ticket | Status in this plan |
|---|---|
| #60 | Phase 0 — commit `ingest_protocol_native.py` + `protocol_native.py` |
| #61 | Phase 1 — kamino renderer (parsed prose per vault) |
| #62 | Phase 0 — drift endpoints ship inside `protocol_native.py`; verify, no separate script needed |
| #63 | Phase 1 — jupiter renderer (per-token prose) |
| #64 | Phase 1 — jito `_render_tip_floor_payload` |
| #65 | Phase 1 — sanctum endpoint fix-or-drop (research) |
| #66 | DONE (commit 1c0ab76) — paysh renderer; re-ingest in Phase 2 |
| #67 | **CLOSE — already correct.** `bazaar_manifest` is not in any `must_cite_provider_kinds` list in `tests/eval/suites/defi_trade_rubric_suite.json`. No change needed. |
| #68 | Phase 1 — `as_of_date` chunk field |
| #72 | Phase 2 — voyage-finance-2 A/B (after corpus is rebuilt) |

`#69`/`#70`/`#71` are S35/S34 work — not in this plan.

## File map

| File | Responsibility | Phase |
|---|---|---|
| `scripts/protocol_native/ingest_protocol_native.py` | 5-protocol ingest CLI (currently worktree-only) | 0 |
| `packages/gecko-core/src/gecko_core/sources/protocol_native.py` | Endpoint defs + `render_chunk()` renderer (worktree-only) | 0, 1 |
| `packages/gecko-core/src/gecko_core/db/mongo_chunks.py` | Chunk insertion — add `as_of_date` field | 1 |
| `packages/gecko-core/tests/sources/test_protocol_native.py` | Renderer unit tests (new) | 1 |
| `tests/eval/scripts/score_defi_trade_rubric.py` | Rubric scorer (read-only — used for measurement) | 2 |

---

## Phase 0 — Reproducibility (ticket #60, #62)

**Owner:** main session (mechanical). **Blocks:** all of Phase 1.

### Task 0.1: Commit the protocol-native ingest pipeline

**Files:**
- Create: `scripts/protocol_native/ingest_protocol_native.py` (from worktree)
- Create: `packages/gecko-core/src/gecko_core/sources/protocol_native.py` (from worktree)

- [ ] **Step 1: Identify the canonical worktree copy.** Compare the 5 worktree copies of `ingest_protocol_native.py` by mtime + `diff`. Pick the newest that also has a sibling `protocol_native.py`. Candidate: `.claude/worktrees/agent-abe71993a20ba2a63/`.

- [ ] **Step 2: Copy both files onto the current branch.**

```bash
SRC=.claude/worktrees/agent-abe71993a20ba2a63
cp "$SRC/scripts/protocol_native/ingest_protocol_native.py" scripts/protocol_native/ingest_protocol_native.py
cp "$SRC/packages/gecko-core/src/gecko_core/sources/protocol_native.py" packages/gecko-core/src/gecko_core/sources/protocol_native.py
```

- [ ] **Step 3: Verify it imports + lints.**

```bash
uv run python -c "import gecko_core.sources.protocol_native as m; print('endpoints:', [n for n in dir(m) if n.endswith('_ENDPOINTS')])"
uv run ruff check scripts/protocol_native/ingest_protocol_native.py packages/gecko-core/src/gecko_core/sources/protocol_native.py
```
Expected: prints `KAMINO_ENDPOINTS, DRIFT_ENDPOINTS, JUPITER_ENDPOINTS, SANCTUM_ENDPOINTS` (drift confirms #62 — no separate drift script needed); ruff clean.

- [ ] **Step 4: Dry-run the CLI (no network).**

```bash
uv run python scripts/protocol_native/ingest_protocol_native.py --dry-run --protocols kamino
```
Expected: prints the planned endpoint calls, writes nothing.

- [ ] **Step 5: Commit (local only — no push).**

```bash
git add scripts/protocol_native/ingest_protocol_native.py packages/gecko-core/src/gecko_core/sources/protocol_native.py
git commit -m "feat(s33-#60): commit protocol_native ingest pipeline from worktree"
```

**Exit gate:** both files tracked on the branch; import + ruff + dry-run clean.

---

## Phase 1 — Renderer Quality (#61, #63, #64, #65, #68)

**Owner:** `data-engineer` subagent (single coordinated edit — kamino/jupiter/jito/sanctum all share `protocol_native.py`). **Blocked by:** Phase 0.

### Task 1.1: Per-entity parsed-prose renderers

**File:** Modify `packages/gecko-core/src/gecko_core/sources/protocol_native.py` (`render_chunk` ~line 752; endpoint blocks: kamino 74–135, drift 137–335, jupiter 337–575, sanctum 576–719).

**Spec for the data-engineer:**
- The current `render_chunk(ep, body_text, as_of_iso)` pretty-prints JSON and wraps it in a prose header. The trade panel cannot cite JSON blobs (this is the `citation_relevance=0.25` root cause).
- Replace the generic JSON dump with **per-endpoint parsed prose**: when a payload is a list of entities (kamino vaults, jupiter tokens), emit **one chunk per entity** as a sentence-shaped paragraph (`"Kamino JLP vault: APY 38.4%, TVL $X, …"`), not a single JSON blob.
- Add `_render_tip_floor_payload()` for jito tip-floor (#64) — flatten the percentile ladder into prose (`"Jito tip floor (50th pct): 0.001 SOL; 75th: …"`).
- Pattern reference: the paysh fix in `packages/gecko-core/src/gecko_core/sources/paysh_live.py` (`_flatten_json_to_prose`, commit 1c0ab76) — replicate that shape.
- Every chunk keeps a provenance header: `"Protocol-native API: <protocol>/<endpoint> (as of <date>)."`

**TDD:** new `packages/gecko-core/tests/sources/test_protocol_native.py` — for each renderer, assert `"{" not in chunk_text and "}" not in chunk_text`, assert per-entity splitting (≥2 chunks from a 2-element list), assert the provenance header prefix.

**Exit gate:** zero `{`/`}` in any rendered chunk; list payloads split per-entity; all new tests green; full `protocol_native` test file passes.

### Task 1.2: `as_of_date` chunk field (#68)

**Files:** Modify `protocol_native.py` (thread `as_of_iso` into the chunk dict) + `packages/gecko-core/src/gecko_core/db/mongo_chunks.py` (~line 243–299, persist `as_of_date`).

**Spec:** `protocol_native` chunks currently carry `captured_at` (ingest time) but not `as_of_date` (data-as-of date). Add `as_of_date` to the chunk document. **TDD:** assert an inserted `protocol_native` chunk has a non-null `as_of_date`.

**Exit gate:** new `protocol_native` chunks carry `as_of_date`; insertion test green.

### Task 1.3: Sanctum endpoint (#65)

**Owner:** `data-engineer` or `solana-researcher`. **Spec:** the sanctum APY endpoint in `protocol_native.py` (~line 691) is a fragile `sanctum-extra-api.ngrok.dev` tunnel returning 0.0 APY. Find the stable public sanctum APY endpoint (check `learn.sanctum.so` / sanctum docs). If none exists, **drop sanctum** from `SANCTUM_ENDPOINTS` and from the ingest protocol list — a dropped source beats a 0.0-APY source.

**Exit gate:** sanctum either returns real APY or is removed; no 0.0-APY chunks enter the corpus.

---

## Phase 2 — Re-ingest + Measure (#66 re-ingest, #72)

**Owner:** main session. **GATED — requires explicit founder go-ahead** (real x402 spend + prod Mongo writes + LLM eval cost). **Blocked by:** Phase 1.

### Task 2.1: Re-ingest protocol-native + paysh

- [ ] Run `uv run python scripts/protocol_native/ingest_protocol_native.py --protocols kamino,drift,jupiter,jito` (prod Mongo write).
- [ ] Re-run the paysh ingest (the 16-protocol `$10`-cap line) — the `DEFAULT_CHUNK_WORDS=150` fix is already applied; expect ~50+ chunks vs the prior 16.
- [ ] Verify chunk shape via the Mongo sample script (`chunks_collection`, `provider_kind` filter) — expect parsed prose, no `{`.

### Task 2.2: Rubric measurement

- [ ] `set -a; source .env; set +a`
- [ ] `uv run python -m tests.eval.scripts.score_defi_trade_rubric --tier basic --tag s33-post-chunks`
- [ ] Compare to the S33-instrumented baseline: expect `pkCov` 0.00 → 0.70+, `citation_relevance` 0.25 → 0.45+.

### Task 2.3: voyage-finance-2 A/B (#72)

- [ ] With the rebuilt corpus, A/B `voyage-3-large` vs `voyage-finance-2` on `citation_relevance` using the same fixtures. Decision feeds S34.

**Exit gate (S33 done):** zero raw-JSON chunks in corpus; `pkCov ≥ 0.70`; `citation_relevance ≥ 0.45`; voyage A/B result recorded.

---

## Self-review notes

- Spec coverage: all 10 S33 tickets accounted for (#67 closed as already-correct, #69/#70/#71 explicitly deferred to S34/S35).
- #62 resolves inside #60 — drift endpoints already live in `protocol_native.py`; Step 3 verifies this.
- Phase 2 is gated, not auto-fired: it spends real money and writes prod data.
