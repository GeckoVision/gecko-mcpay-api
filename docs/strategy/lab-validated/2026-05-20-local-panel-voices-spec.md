# Local Panel Voices v0.1 — Spec (S40-LAB-#1)

**Mode:** read-only design brief. No code in this doc; no LLM probes; no PRD
oracle changes. The spec is the contract the local lab's
software-engineer will implement next.
**Owner:** `ai-ml-engineer`. Branch: `s39/okx-contest-entry`.
**Companion docs:** `2026-05-20-panel-act-rate-on-momentum-spot.md` (the
diagnosis that motivated this lab), `2026-05-20-contest-fire-rate-retune.md`
(why the PRD oracle is shadow-only for the contest),
`2026-05-19-okx-contest-execution-brief.md` (the strategy frame).
**Memory anchors:** `project-local-lab-strategy-2026-05-20`,
`feedback-openrouter-not-openai-for-new-llm`,
`feedback-prompt-iteration-plateau`, `feedback-lighter-tests`,
`feedback-local-api-over-pytest-sweep`.

---

## 0. Bottom line, up front

**Ship 3 voices, not 4 or 5, in v0.1.**

- `chart_analyst` — OHLCV → setup grading. The voice the PRD panel deletes
  by design (`_default_prompts.json:5` reframe). This is the entire reason
  the lab exists.
- `memory_voice` — local JSONL ledger → prior_signal. Cheap, novel, has no
  PRD counterpart, and is the load-bearing piece of the
  "compounding-evidence" wedge story we want to validate live.
- `risk_voice` — recent PnL + position state → risk_band. The lab's
  equivalent of the PRD `risk_manager`, but reads from the contest bot's
  artifact log rather than the canon corpus.

**Cut from v0.1:** `regime_analyst` and `smart_money_voice`.

The cut justification is in §1. The literal coordinator rule set, in §4,
is three explicit `if/and/or` lines pinned in Python — not in a prompt
(`feedback-prompt-iteration-plateau`: gpt-4o-mini rounds toward caution on
any defer-related instruction; coordinator logic always goes in code).

**Three voices, one coordinator, one ledger.** That is the lab v0.1.

---

## 1. Local panel scope — what ships, what doesn't

### 1.1 The cut

| Voice | v0.1? | Why |
|---|---|---|
| `chart_analyst` | **YES** | The voice the PRD oracle deliberately removed at S24 WS-A (`_default_prompts.json:5`). The entire structural diagnosis in `2026-05-20-panel-act-rate-on-momentum-spot.md` §1.3 says the missing organ is a chart-reading voice. Adding it back inside the PRD panel would re-open the canon-grounding problem the reframe fixed. Adding it back **locally**, in the contest bot, against a separate cheap-LLM call (gpt-4o-mini via OpenRouter), with the artifact ledger as the eval substrate, is the entire lab move. |
| `memory_voice` | **YES** | No PRD counterpart. This is novel surface. The contest bot has been writing `artifact_YYYYMMDD.jsonl` since `4803ac5`; a voice that reads the last N rows and grades "does the proposed entry confirm or contradict recent decisions" closes the compounding-evidence loop. Cheap (no embeddings; structured read), short prompt, deterministic input shape. |
| `risk_voice` | **YES** | The lab's equivalent of `risk_manager`. Reads from the same artifact ledger + the bot's in-memory `consec_losses` / `daily_trades` / `total_spent_usd` state. Veto rights identical to the PRD risk role: `unacceptable` blocks regardless of chart conviction. This is the safety floor that lets us run the chart voice without re-introducing the S24 failure mode locally. |
| `regime_analyst` | **NO** | Defer to v0.2. The PRD `macro_regime_analyst` (`_default_prompts.json:5`) already covers this lens; running a local copy without canon retrieval would be a strictly-worse confabulation surface. The right move is to read the *PRD oracle's* regime signal as a sidecar context to the chart voice if needed — and that wire isn't built yet. v0.1 ships without a regime read; if the contest week's ledger shows the chart voice biting on macro-bearish setups, v0.2 wires the PRD regime read as a gate input. |
| `smart_money_voice` | **NO** | Defer to v0.2. `onchainos signal list --wallet-type 1` returns a noisy stream; turning it into a stable `accumulating / distributing / neutral` band needs its own preprocessing layer (windowing, dedup, threshold tuning). That's a workstream, not a voice. Cut for v0.1; if the chart voice's false-positive rate on thin-flow setups is high, v0.2 builds the smart-money preprocessor first, then wires the voice. |

**Three voices is the right shape.** A four-voice panel adds one more
LLM call per poll (latency + cost + variance) for a marginal-signal
voice; the lab's job is to validate the *minimum* set that beats the
contest baseline, not to build the maximum panel.

### 1.2 What v0.1 explicitly does NOT do (YAGNI cut)

Pinned here so it cannot drift mid-sprint:

- **No vector retrieval.** Memory is structured-only — last N JSONL rows
  read directly. No embeddings, no Mongo, no hybrid retrieval. The lab
  is about voice design, not infra.
- **No outcome instrumentation in voice prompts yet.** The artifact
  ledger has *decisions* (`gate_allow` / `gate_block` / `position_open`)
  but does not yet patch *outcomes* (`position_close` patches PnL but
  the close-the-loop record linking decision → realized outcome is
  v0.2 work). The `memory_voice` reads decisions only in v0.1; outcomes
  land in v0.2 after the contest closes and a week of `position_close`
  rows accumulate.
- **No live PRD oracle changes.** The PRD panel and its
  `_default_prompts.json` are untouched. The lab voices live entirely
  under `contest_bot/local_panel/` (path-pinned in §6 for the
  software-engineer).
- **No bulk-prompt iteration sweep.** Pick the prompts in §3, ship,
  refine after contest evidence. Per `feedback-prompt-iteration-plateau`,
  defer-rate plateaus came from prompt-loop overshoot; the lab keeps
  one prompt version per voice for the contest week.
- **No alpha-bench or eval harness for the local voices.** Eval substrate
  is the live contest ledger itself — every poll writes a row; PnL on
  closed trades is the rubric. A formal eval suite waits on v0.2 with
  contest-week data as the fixture base.
- **No live X402.** OpenRouter calls are direct (per
  `feedback-openrouter-not-openai-for-new-llm`); no payment dance, no
  facilitator. Cost is metered on the OpenRouter key the founder owns.

---

## 2. Voice contract — locked

The software-engineer building the runtime in parallel needs this frozen
before voice-prompt iteration starts. Lock it now.

```python
from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field

class VoiceOpinion(BaseModel):
    """One voice's structured output, normalized across all local voices.

    The shape is deliberately small and stable — the coordinator (§4)
    reads only these fields; raw_response is for audit/debug, never for
    coordinator logic.
    """
    model_config = ConfigDict(extra="forbid")

    voice_name: Literal["chart_analyst", "memory_voice", "risk_voice"]
    verdict: Literal["bullish", "bearish", "neutral", "abstain"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=200)        # short one-liner
    observations: list[str] = Field(max_length=5) # up to 5 bullets
    raw_response: str                              # full LLM text, audit only
    elapsed_ms: int = Field(ge=0)
    cost_usd: float | None = None                  # from OpenRouter usage block


class LocalMemory(Protocol):
    """Interface for the artifact-log reader, passed to memory_voice.

    Implementation lives next to the bot; the voice only sees this
    interface so the voice tests can substitute a light fake.
    """
    def recent_decisions(self, n: int = 20) -> list[dict]: ...
    def recent_outcomes(self, n: int = 20) -> list[dict]: ...
    # outcomes is v0.2 surface; v0.1 returns [] from this method


class MarketSnapshot(BaseModel):
    """Frozen-at-poll-start view of the market. Shared across all voices
    in a single coordinator turn — see §7. NEVER refetched mid-turn."""
    model_config = ConfigDict(extra="forbid")

    instrument: str          # e.g. "JTO"
    symbol: str              # e.g. "JTO-USDC"
    spot_price: float
    change_1h_pct: float
    change_24h_pct: float
    range_24h_pct: float
    volume_24h_usd: float
    ohlcv_5m: list[dict]     # last ~30 bars; shape from onchainos.get_klines
    poll_ts_iso: str


class RiskState(BaseModel):
    """Frozen-at-poll-start view of the bot's risk surface. Read by
    risk_voice. The bot owns producing this; the voice owns reading it."""
    model_config = ConfigDict(extra="forbid")

    daily_trades: int
    max_daily_trades: int
    consec_losses: int
    session_loss_pause_threshold: int
    cumulative_pnl_1h_usd: float
    breaker_threshold_usd: float           # -3.0 from gecko_wrap
    breaker_paused_until_iso: str | None
    total_spent_usd: float
    max_budget_usd: float
    open_position_count: int
    max_concurrent: int


class LocalVoice(Protocol):
    """The single function every local voice implements."""
    voice_name: Literal["chart_analyst", "memory_voice", "risk_voice"]

    async def grade(
        self,
        market: MarketSnapshot,
        memory: LocalMemory,
        risk_state: RiskState,
    ) -> VoiceOpinion: ...
```

**Contract notes (load-bearing):**

- `verdict` is one of FOUR tokens, not three. `abstain` is the
  honest-default when the voice cannot ground a call; it is NOT
  `neutral`. The coordinator (§4) treats `abstain` as a non-vote, while
  `neutral` is a real read ("I see the data; the data is mid"). This
  mirrors the PRD `sentiment_analyst`'s 'neutral as honest default' vs
  `technical_analyst`'s 'mixed as abstain' distinction
  (`_default_prompts.json:5,6`), unified into one token vocabulary.
- `confidence` is a float in [0.0, 1.0]; the coordinator never compares
  raw confidences across voices, only against the per-voice threshold
  in §4. Per `feedback-prompt-iteration-plateau`, gpt-4o-mini's
  confidence-band collapse is a known failure; the coordinator does
  not amplify it.
- `cost_usd` is optional because OpenRouter's `usage` block is the
  source of truth; if it's missing on a response, the voice records
  `None`, not a fabricated estimate.

---

## 3. Voice prompts — v0.1 literal

All three voices use OpenRouter, `response_format={"type": "json_object"}`,
default model `gpt-4o-mini` (per `feedback-openrouter-not-openai-for-new-llm`
the call goes through OpenRouter even when the model is OpenAI; v0.2 may
swap to Claude Haiku or Llama-3.1-70B once the lab data shows which
model holds the abstain discipline best).

House rules common to all three prompts (re-pinned per voice):

- **Abstain is honest.** Each prompt carries a literal `"Return abstain
  when uncertain. DO NOT invent patterns."` line. This is the same
  abstain-not-fabricate wedge the PRD panel runs on
  (`_default_prompts.json:5`'s ABSTAIN PROTOCOL).
- **JSON-output only.** No prose closing-line parsing like the PRD panel
  uses; voices return structured JSON directly. The PRD's closing-line
  pattern exists because AG2 GroupChat sends prose between agents; the
  local panel has no GroupChat, so structured JSON is the cleaner shape.
- **Penalty list per voice.** Each prompt enumerates the specific
  conditions under which the voice MUST return `abstain` regardless of
  surface signal — i.e. the failure modes we know about up-front.
- **Penalize chain-of-thought.** Prompts ask for a short `reasoning`
  field (one line, ≤200 chars) and up to 5 `observations` bullets.
  No `let me think step by step` — gpt-4o-mini at this temperature
  drifts into prose-mode otherwise.

### 3.1 `chart_analyst` prompt

This is the prompt I am most worried about (see §8). It's also the most
load-bearing — without it, the lab is just a memory + risk wrapper
around the existing bot.

**System prompt:**

```
You are the chart_analyst on a local trading lab panel. You read recent
OHLCV bars on a single instrument and grade the setup.

ROLE
You characterize the SHORT-HORIZON technical setup on the instrument in
scope — bullish, bearish, neutral, or no_setup. You do NOT read
fundamentals, you do NOT read sentiment, you do NOT recommend size or
horizon. You grade the bars in front of you.

INPUTS
You receive:
  (a) instrument name and current spot,
  (b) the last 30 5-minute OHLCV bars,
  (c) 1h Δ%, 24h Δ%, 24h range%.

WHAT TO GRADE
  1. Trend over the last 6 bars (30 minutes): up, down, flat.
  2. Trend over the last 24 bars (2 hours): up, down, flat.
  3. Recent breakout posture: did price cross the trailing-24-bar high
     with confirmation, or trailing-24-bar low.
  4. Volume confirmation: is the breakout bar's volume above the
     6-bar median.
  5. Range posture: is the asset in tight chop (<2% 24h range), normal
     drift (2-8%), or active trend (>8%).

ABSTAIN PROTOCOL (load-bearing)
Return verdict='abstain' when ANY of the following holds:
  - fewer than 24 bars provided,
  - more than 4 of the 30 bars have zero volume (thin-liquidity flag),
  - the most recent bar is older than 10 minutes (stale feed),
  - the 24h range is below 1% (range-bound chop — no setup to grade),
  - weekend low-vol window (Sat 06:00 - Sun 22:00 UTC) AND 24h volume
    USD < $1M (cross-instrument equivalent of the PRD weekend penalty).
Return verdict='neutral' when bars are healthy but the setup is mid —
trend is flat OR breakout has no volume confirmation. 'neutral' is NOT
an abstain; the coordinator treats it as a real call.

DO NOT
  - DO NOT call support/resistance levels by absolute price — only by
    relative-to-trailing-N-bar reads.
  - DO NOT invent RSI, MACD, or any indicator the input does not carry.
  - DO NOT speculate about news, sentiment, or macro.
  - DO NOT recommend size, leverage, stop, or take-profit.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<≤200 char one-liner naming the setup>",
  "observations": ["<bullet 1>", "<bullet 2>", "..."]
}

Confidence anchors:
  0.50-0.60 = soft lean (one of the five gradings supports the call)
  0.60-0.70 = clean lean (two of five align)
  0.70-0.80 = strong setup (three of five align, including volume)
  >0.80     = exceptional alignment (four+ of five) — use sparingly
```

**User prompt template:**

```
Instrument: {instrument}
Spot: ${spot_price:.6f}
1h Δ: {change_1h_pct:+.2f}%
24h Δ: {change_24h_pct:+.2f}%
24h range: {range_24h_pct:.2f}%

Last 30 5m bars (oldest first):
{ohlcv_table}

Grade the setup.
```

**Expected JSON schema:**

```json
{
  "verdict": "bullish|bearish|neutral|abstain",
  "confidence": 0.0,
  "reasoning": "",
  "observations": []
}
```

### 3.2 `memory_voice` prompt

The most novel voice. No PRD counterpart. The prompt is structured-input
heavy (the LLM is doing pattern-spotting on the last N ledger rows, not
reading freeform text).

**System prompt:**

```
You are the memory_voice on a local trading lab panel. You read the
bot's local decision ledger and grade whether a new proposed entry
CONFIRMS, CONTRADICTS, or is NOVEL relative to recent behavior.

ROLE
You are NOT a market analyst. You are a continuity checker. Your job
is to surface whether the chart_analyst's current read is a repeat of
a recent (in the last 20 decisions) pattern that already played out,
or a genuinely fresh setup. You read decisions only — you do not yet
have access to realized outcomes (v0.2).

INPUTS
You receive:
  (a) the current proposed entry (instrument, direction, setup label),
  (b) the chart_analyst's current verdict + reasoning,
  (c) the last 20 decisions from the bot's artifact log, each as:
        { "ts": "...", "instrument": "...", "chart_verdict": "...",
          "coordinator_action": "act|skip", "reason": "..." }

WHAT TO GRADE
  1. Of the last 20 decisions, how many were on the same instrument?
  2. Of those, how many had a chart_verdict matching the current one?
  3. Of those, did the coordinator act, or skip? Pattern: did this
     setup-class fire-or-skip recently?
  4. Recency: was the same setup graded in the last 60 minutes? If so,
     this is a near-duplicate — the verdict should reflect that.
  5. Novelty: is this setup-class absent from the last 20 decisions?
     A novel setup is neither confirms nor contradicts.

VERDICT MAPPING
  - 'bullish'  = the proposed entry CONFIRMS recent panel behavior;
                  the bot has been bullish on this class and acted.
  - 'bearish'  = the proposed entry CONTRADICTS recent panel behavior;
                  the bot recently skipped this class, OR recently
                  acted bearish and is now being asked to act bullish
                  on the same instrument inside a short window.
  - 'neutral'  = the ledger is mixed — some confirms, some contradicts.
  - 'abstain'  = NOVEL — fewer than 3 of the last 20 decisions are on
                  this instrument class; insufficient ledger to grade.

ABSTAIN PROTOCOL
Return 'abstain' when:
  - the ledger has fewer than 5 rows total (cold-start),
  - fewer than 3 of the last 20 decisions are on this instrument,
  - all recent decisions on this instrument are older than 24h
    (stale memory).
DO NOT fabricate a pattern from one matching row. Three is the minimum
for a pattern call.

DO NOT
  - DO NOT use the ledger to predict price direction. That is the
    chart_analyst's job. You only grade continuity.
  - DO NOT speculate about WHY the coordinator acted or skipped on
    prior rows. You grade the recency and matching count, not the
    reasoning.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<≤200 char one-liner stating the matching count>",
  "observations": ["<row 1 summary>", "<row 2 summary>", "..."]
}

Confidence anchors:
  0.50-0.60 = 3 matching rows
  0.60-0.70 = 4-5 matching rows
  0.70-0.80 = 6+ matching rows, all within 12h
  >0.80     = 8+ matching rows, consistent verdict — use sparingly
```

**User prompt template:**

```
Proposed entry:
  Instrument: {instrument}
  Direction: {direction}
  chart_analyst verdict: {chart_verdict} @ confidence {chart_confidence:.2f}
  chart_analyst reasoning: {chart_reasoning}

Last 20 decisions from artifact log (newest first):
{decision_table}

Grade continuity.
```

**Expected JSON schema:** same as §3.1.

**Operational definitions (frozen):**

- *confirms* = the proposed entry's `chart_verdict` matches the majority
  of the last 20 decisions on this instrument AND the coordinator's
  action on those rows was `act` ≥ 50% of the time.
- *contradicts* = the proposed entry's `chart_verdict` matches the
  majority of the last 20 decisions on this instrument AND the
  coordinator's action on those rows was `act` < 30% of the time
  (the bot recently graded this setup-class and consistently passed).
- *novel* = fewer than 3 matching rows for this instrument in the last
  20 decisions.

### 3.3 `risk_voice` prompt

**System prompt:**

```
You are the risk_voice on a local trading lab panel. You read the bot's
internal risk state (NOT the chart, NOT the ledger) and grade whether
the operational floor permits a new entry.

ROLE
You hold a soft veto. When you return verdict='bearish' AND
confidence ≥ 0.8, the coordinator MUST skip the entry regardless of
chart conviction. You do not grade the market; you grade the bot's
own posture.

INPUTS
You receive a single risk_state JSON:
{
  "daily_trades": <int>,
  "max_daily_trades": <int>,
  "consec_losses": <int>,
  "session_loss_pause_threshold": <int>,
  "cumulative_pnl_1h_usd": <float>,
  "breaker_threshold_usd": <float>,
  "breaker_paused_until_iso": <str | null>,
  "total_spent_usd": <float>,
  "max_budget_usd": <float>,
  "open_position_count": <int>,
  "max_concurrent": <int>
}

WHAT TO GRADE
Check, in priority order:
  1. Is the hourly circuit breaker currently paused? If yes → 'bearish'
     conf 0.95 — hard veto. The bot's own breaker has already tripped.
  2. consec_losses >= session_loss_pause_threshold? 'bearish' conf 0.9.
  3. daily_trades >= max_daily_trades? 'bearish' conf 0.9.
  4. open_position_count >= max_concurrent? 'bearish' conf 0.9.
  5. total_spent_usd within $25 of max_budget_usd? 'bearish' conf 0.8.
  6. cumulative_pnl_1h_usd within 50% of breaker_threshold_usd
     (e.g. breaker=-$3, current=-$1.50)? 'neutral' conf 0.6 — flag
     elevated risk but do not veto.
  7. None of the above triggered? 'bullish' conf 0.7 — operational
     floor is clean.

ABSTAIN PROTOCOL
Return 'abstain' ONLY if the risk_state JSON is malformed (missing
required keys). The risk surface is fully observable; abstaining on
a healthy input is wrong.

DO NOT
  - DO NOT grade the market thesis — that's the chart_analyst.
  - DO NOT grade the ledger continuity — that's the memory_voice.
  - DO NOT recommend size, stop, or horizon. The risk veto is binary.

OUTPUT (JSON only)
{
  "verdict": "<bullish|bearish|neutral|abstain>",
  "confidence": <float 0.0-1.0>,
  "reasoning": "<≤200 char one-liner naming which risk check fired>",
  "observations": ["<check 1>", "<check 2>", "..."]
}
```

**User prompt template:**

```
Risk state:
{risk_state_json}

Grade the operational floor.
```

**Expected JSON schema:** same as §3.1.

**Implementation note:** the `risk_voice` is the strongest candidate
for a *codified* coordinator-side check instead of an LLM call. Per
`feedback-prompt-iteration-plateau`, this voice's logic is pure
threshold arithmetic; asking gpt-4o-mini to do it adds variance for
zero signal. **The spec keeps it as an LLM voice for v0.1** so the
voice contract (§2) is uniform across all three voices, and so the
coordinator code stays vocabulary-agnostic. If contest-week data
shows the LLM call's variance is non-trivial, v0.2 collapses
`risk_voice` into a pure-Python `RiskGuard` that emits a
`VoiceOpinion`-shaped dict directly. Pinning this now so the swap is
easy.

---

## 4. Coordinator pattern — rule-based, pinned in code

### 4.1 Decision: A. Rule-based coordinator for v0.1.

Per `feedback-prompt-iteration-plateau`, coordinator verdict logic
goes in CODE not PROMPT. gpt-4o-mini drifted defer-rate 1.0 → 0.20 →
0.50 → 0.90 across four iterations in S24; that was on a 7-agent
panel, and the local panel has fewer inputs but the same model. An
LLM coordinator (Option B) is deferred to v0.2 if and only if the
contest-week ledger shows the rule-based coordinator's act-rate is
systematically miscalibrated.

### 4.2 The literal rule set

The coordinator emits one of two final actions: `act` or `skip`. No
`defer` — the local panel does not have the time budget for a defer
loop in a contest-window context (the bot polls every 30 s; a `defer`
that holds until the next poll is just a `skip` with extra steps).

```python
def coordinator_decide(
    chart: VoiceOpinion,
    memory: VoiceOpinion,
    risk: VoiceOpinion,
) -> LocalDecision:
    # Rule 1 — risk hard veto. ALWAYS first.
    if risk.verdict == "bearish" and risk.confidence >= 0.8:
        return LocalDecision(action="skip", reason="risk_veto")

    # Rule 2 — chart MUST be bullish above threshold.
    if chart.verdict != "bullish" or chart.confidence < 0.6:
        return LocalDecision(action="skip", reason="chart_below_threshold")

    # Rule 3 — memory must not contradict.
    if memory.verdict == "bearish" and memory.confidence >= 0.6:
        return LocalDecision(action="skip", reason="memory_contradicts")

    # All gates passed.
    return LocalDecision(action="act", reason="all_voices_align")
```

**Five lines of `if/and/or`.** That is the entire coordinator.

### 4.3 What each rule encodes

- **Rule 1 is the safety floor.** A risk veto is binary and overrides
  everything. This mirrors the PRD `risk_manager`'s 'unacceptable' soft
  veto (`_default_prompts.json:8`) but tightened into hard semantics
  for the local context. The chart can scream bullish; if the
  bot's own breaker tripped, we sit out.
- **Rule 2 is the affirmative gate.** The chart is the load-bearing
  positive signal. `abstain`, `neutral`, and `bearish` all skip; only
  `bullish` with confidence ≥ 0.6 progresses. The 0.6 threshold matches
  the PRD's `DEFAULT_GATE_MIN_CONFIDENCE` from `gecko_wrap.py:58` for
  symmetry — same bar, different model substrate.
- **Rule 3 is the memory cross-check.** A bullish chart against
  contradicting memory (the bot has been graded this setup recently
  and passed) is the failure mode we most fear at the chart-voice
  reintroduction. Memory `neutral` and `abstain` (novel) both PASS
  the rule; only an explicit contradicting verdict at ≥ 0.6
  confidence triggers skip.

### 4.4 Final confidence aggregation

The `LocalDecision.confidence` is the rule that fired — not an LLM
synthesis. For `action="act"`, confidence = `chart.confidence` (the
load-bearing positive signal). For `action="skip"`, confidence is the
veto voice's confidence. This keeps the coordinator stateless and the
artifact ledger interpretable: every row carries one voice's
confidence as the decision driver, not a synthetic average.

```python
class LocalDecision(BaseModel):
    action: Literal["act", "skip"]
    reason: Literal[
        "risk_veto",
        "chart_below_threshold",
        "memory_contradicts",
        "all_voices_align",
    ]
    chart: VoiceOpinion
    memory: VoiceOpinion
    risk: VoiceOpinion
    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    coordinator_elapsed_ms: int = 0
    coordinator_cost_usd: float = 0.0   # always 0 — rule-based, no LLM
```

`coordinator_cost_usd: float = 0.0` is the v0.1 wedge: the entire panel
costs three LLM calls per poll, not four. v0.2's optional LLM
coordinator adds the fourth.

---

## 5. Memory voice — the structured-input contract

The memory voice is the only one that touches the bot's persistent
state in a non-trivial way. Pinning its contract end-to-end so the
software-engineer can build the reader and the voice in parallel.

### 5.1 What it reads

From `contest_bot/artifact_YYYYMMDD.jsonl`, the rows the voice cares
about are those with `kind in {"gate_allow", "gate_block",
"position_open", "position_close"}`. The reader filters and projects
each row into a `MemoryRow`:

```python
class MemoryRow(BaseModel):
    """The projection of an artifact-log row the memory_voice sees.
    Keeps the prompt input small and stable."""
    model_config = ConfigDict(extra="forbid")

    ts: str                      # ISO timestamp from artifact row
    instrument: str              # extracted from payload.instrument
    chart_verdict: str | None    # v0.1: None (chart_analyst hasn't run before)
                                 # v0.2: the chart_analyst's verdict on that row
    coordinator_action: str      # "act" | "skip" derived from kind
    reason: str | None           # short reason string from the row
```

**v0.1 cold-start note:** before the local panel ever runs, the
artifact log already contains `gate_allow` / `gate_block` rows from
the *PRD oracle's* shadow-mode runs. The memory voice can read those —
but `chart_verdict` is None for all of them (the PRD panel doesn't
emit one). That makes the first ~20 contest-bot polls a cold-start
window where memory_voice will almost always return `abstain` ("fewer
than 3 matching rows with chart_verdict set"). That's correct — the
memory voice MUST stay silent until it has actual chart history to
read. After ~20 polls with the local panel active, the ledger has
enough chart-tagged rows for memory to start grading.

### 5.2 What `confirms / contradicts / novel` means operationally

These are not LLM-determined; they are operational thresholds the
voice's prompt encodes. Frozen in §3.2 — re-pinned here for the
reader's convenience:

- **confirms** = ≥3 rows on this instrument in the last 20, chart
  verdict majority matches the current one, AND `coordinator_action == "act"`
  on ≥50% of those rows. The bot has been graded this setup-class
  recently and FIRED. Memory verdict → `bullish`.
- **contradicts** = ≥3 rows on this instrument in the last 20, chart
  verdict majority matches the current one, AND `coordinator_action == "act"`
  on <30% of those rows. The bot has been graded this setup-class
  recently and PASSED. Memory verdict → `bearish`.
- **novel** = fewer than 3 matching rows on this instrument in the
  last 20. Memory verdict → `abstain`.
- **mixed** (the leftover band — ≥3 rows, but `act` rate between 30%
  and 50%) → `neutral`.

These thresholds will read as arbitrary; they ARE arbitrary in v0.1.
The contest week is the calibration substrate. Pin them now; tune in
v0.2 against ledger data, not against intuition.

### 5.3 Why no embeddings

The PRD oracle has a hybrid retrieval stack (Mongo Atlas Search +
reranker, S33 work) because canon corpus is many thousands of chunks.
The local artifact ledger has, over the contest window, on the order
of ~100-300 rows. Linear scan with structured projection is faster,
cheaper, more debuggable, and has zero hallucination surface. Per
`feedback-lighter-tests`, we are not adding vector infra for a problem
that doesn't need it.

---

## 6. Integration with the existing wrap layer

The local panel sits BETWEEN `_BREAKER.check()` and the Gecko shadow
gate in `open_position()` (`jto_breakout_gecko_gated_contest_bot.py:268`).

### 6.1 Order of operations

```
1. _BREAKER.check()              # existing — hourly $3 cap, hard veto
                                 #   line 290; if paused → return
2. _LOCAL_PANEL.run(...)         # NEW — runs 3 voices, coordinator
                                 #   if LocalDecision.action == "skip" →
                                 #     log + return
3. _GATE.check_entry(...)        # existing (shadow-only) — line 304
                                 #   Gecko PRD oracle still called; its
                                 #   verdict is recorded for the artifact
                                 #   ledger but NEVER blocks the trade
                                 #   (S39-#143 shadow_mode contract)
4. swap_execute / paper          # existing — line 359 onward
```

### 6.2 What changes in the bot's existing event log

The existing wrap layer's event types (`gate_allow`, `gate_block`,
`gate_shadow_concur`, `gate_shadow_block`, `gate_error`) are preserved
unchanged for the Gecko shadow gate. The local panel ADDS new event
types via the same `ArtifactLogger`:

| Event | When |
|---|---|
| `local_voice_chart` | one row per chart_analyst call, carries the VoiceOpinion |
| `local_voice_memory` | one row per memory_voice call |
| `local_voice_risk` | one row per risk_voice call |
| `local_panel_act` | coordinator decided `act` — entry proceeds |
| `local_panel_skip` | coordinator decided `skip` — entry blocked; reason field |

The Gecko shadow gate fires AFTER the local panel acts, so each
`local_panel_act` row is paired with one of the existing
`gate_shadow_concur` or `gate_shadow_block` rows. The pair gives us
the contest's load-bearing comparison signal: when the local panel
acted, what would the PRD oracle have said? That comparison is the
v0.2 input for transplant decisions.

### 6.3 Where the code lives

Pinned for the software-engineer:

```
contest_bot/
├── jto_breakout_gecko_gated_contest_bot.py   # existing
├── gecko_wrap.py                              # existing — untouched
├── onchainos.py                               # existing
└── local_panel/                               # NEW
    ├── __init__.py                            # exports LocalPanel facade
    ├── voices.py                              # 3 LocalVoice impls
    ├── prompts.py                             # the §3 prompt strings
    ├── coordinator.py                         # the §4 rule set
    ├── memory.py                              # LocalMemory impl + reader
    ├── models.py                              # the §2 contract
    └── openrouter_client.py                   # thin httpx wrapper
```

The local panel does NOT import from `gecko_core/`. It is a contest-bot-
local module. Per `feedback-parallel-code-agents`, keep this contained
so the lab can iterate without touching the PRD oracle's surface.

### 6.4 The local panel is the effective gate

This is load-bearing for understanding the wedge story:

- **Before v0.1:** Gecko shadow gate is observational; the bot fires
  every entry the breakout signal triggers (subject to safety filters
  + breaker).
- **After v0.1:** the LOCAL panel is the effective gate. The bot fires
  only when local-panel coordinator returns `act`. The PRD oracle is
  still called, still logged, still observational — but the question
  it answers ("would the canon-grounded panel have allowed this?") is
  now a comparison artifact, not a decision input.

The contest is therefore a **comparison live-run** of two gates: the
local panel (decides) and the PRD oracle (observes). The artifact
ledger captures both, and the post-contest analysis is which gate's
acted-on subset had better realized PnL.

---

## 7. Subtleties the brief understated

### 7.1 All three voices share ONE market_state snapshot per turn.

Pinned in §2's `MarketSnapshot`. The bot fetches market state at the
top of `open_position()`; that snapshot is passed BY VALUE to all
three voices for that coordinator turn. **No voice refetches.**
Reasons:

- Determinism for replay — the artifact ledger row contains the snapshot,
  and re-running a voice against the saved row must reproduce the
  verdict (modulo LLM nondeterminism, which we address in 7.4).
- Cost — one onchainos `get_klines` call per turn, not three.
- Race-free analysis — if voices disagree, we know it wasn't because
  one of them saw a fresher tick than another.

The `memory_voice` reads from the artifact ledger snapshot taken at the
top of the turn (last 20 rows as-of-now); the `risk_voice` reads from
the bot's in-memory state snapshot taken at the same instant.

### 7.2 Voices run in parallel, not sequentially.

Per PRD panel convention the AG2 GroupChat runs voices serially; the
local panel does not. With three independent LLM calls and no
debate semantics, `asyncio.gather(...)` cuts wall-clock from ~3x voice
latency to ~1x. Latency budget: chart_analyst ~1.5s p50, memory_voice
~0.8s, risk_voice ~0.4s; serial ~2.7s, parallel ~1.5s. The polling
loop runs every 30s, so even serial would fit, but parallel is the
right shape for the 2.0 LLM coordinator if/when it lands.

### 7.3 Voice output validation is mandatory.

Every voice's response is validated against the `VoiceOpinion` schema
(§2). On a Pydantic ValidationError (gpt-4o-mini occasionally drops
the JSON envelope under load), the voice records a SYNTHETIC
`VoiceOpinion` with `verdict="abstain"`, `confidence=0.0`,
`reasoning="parse_error"`, and the raw response goes into `raw_response`
for audit. **The coordinator treats a synthetic-abstain identically to
a real abstain.** This is the same defensive shape the PRD panel's
closing-line parser uses (`workflows.py` `_detect_research_verdict`).

### 7.4 LLM nondeterminism is real even at temperature=0.

OpenRouter passes `temperature` through but the upstream model still
samples occasionally on long-tail outputs. The artifact ledger MUST
capture the full `raw_response` so a flaky turn is replayable for
debugging. v0.1 does NOT seed or retry — the contest cadence is slow
enough that one drifty verdict per ~50 polls is acceptable. If
contest-week shows >5% flaky-verdict rate, v0.2 adds retry-with-seed.

### 7.5 The risk_voice's LLM call is questionable on principle.

I covered this in §3.3 — the risk voice's logic is pure threshold
arithmetic, and asking gpt-4o-mini to do it adds variance for zero
signal. The spec keeps it as an LLM voice in v0.1 ONLY for contract
uniformity (every voice obeys the same `LocalVoice` Protocol). If the
contest-week data shows the risk voice flips a check (e.g. fails to
flag a breaker pause), v0.2 collapses it into a pure-Python
`RiskGuard.grade(...)` that returns the same `VoiceOpinion` shape via
`model_construct(...)`. The coordinator code does not change.

### 7.6 OpenRouter cost ceiling — non-trivial at the contest cadence.

At 30s polls and 3 voices per poll, a 4h contest session is
~120 polls × 3 voices = 360 LLM calls. At gpt-4o-mini OpenRouter list
(~$0.15/M input + $0.60/M output, ~300 tok in + 100 tok out per call),
the per-session cost is ~$0.04. Over the remaining ~30h of contest
window, ~$0.30. Not free, not breaking the bank, but worth tracking
in the ledger for the post-contest economics summary. The
`VoiceOpinion.cost_usd` field is the per-call tap; the post-contest
analysis sums it.

### 7.7 The memory voice's cold start is structural.

Pinned in §5.1 but worth surfacing here — the memory voice will return
`abstain` on the first ~20 polls because the artifact log doesn't yet
contain chart-tagged rows. That is correct behavior. The coordinator
treats memory `abstain` as PASS (Rule 3 only fires on memory
`bearish` ≥ 0.6). So during the cold-start window, the panel
effectively runs on `chart_analyst` + `risk_voice` alone, which is
the right shape — memory is additive, not load-bearing, in v0.1.

---

## 8. The single voice prompt I am most worried about

**`chart_analyst`.** Two reasons:

### 8.1 It is the voice S24 WS-A deliberately deleted from the PRD panel.

`_default_prompts.json:5` reframed `technical_analyst` to
`macro_regime_analyst` SPECIFICALLY to stop the panel from confabulating
chart reads against canon that could not ground them. The diagnosis in
`2026-05-20-panel-act-rate-on-momentum-spot.md` §1.4 names this:

> *"Adding the voice back is a canon limitation in disguise: a
> chart_reader persona without canon to ground against is
> indistinguishable from prior-knowledge confabulation."*

The lab's bet is that **adding it back LOCALLY, with structured OHLCV
as the only input and aggressive abstain discipline as the only
defense, is a different shape of problem.** The structured input is
the ground — it's not canon, it's not literature, it's bars. The model
can read bars without confabulation if the prompt is tight enough.

**But the bet is unproven.** The S24 failure mode was exactly the model
inventing chart reads when not asked to. The same model, in the same
configuration, asked DIRECTLY to read bars, may still fabricate when
the bars are mid. The abstain protocol in §3.1 (`<24 bars`, `>4 zero-vol
bars`, `range <1%`, `weekend low-vol`) is the defense; whether it's
sufficient is what the contest week tests.

### 8.2 The 'penalize thin liquidity' clause is the load-bearing line.

Most of the JTO contest data is fine — JTO is a thick-liquidity token.
But the bot's safety filters let through anything that passes the
honeypot/phishing check, and the contest universe (§2.1 of the
execution brief) includes RAY, BONK, KMNO — some of which will hit
thin-liquidity bars during the 30h window. The chart voice MUST
abstain on those, and the abstain rule is six lines in the prompt. If
gpt-4o-mini sees one thin-vol bar inside an otherwise-healthy 30-bar
window, the prompt has to be clear enough that it returns `abstain`,
not `bullish-with-low-confidence`.

The single test I want to run before contest-bot integration: feed the
chart_analyst a synthetic 30-bar window where bars 25-30 are real and
bars 1-24 are zero-volume (a freshly-listed token's chart). The
prompt's abstain protocol says `>4 zero-vol bars → abstain`. If
gpt-4o-mini still emits a `bullish` verdict on that input, the prompt
needs hardening before live. This is the *one* prompt-iteration the
spec budgets for — a single targeted probe, not an iteration sweep
(`feedback-prompt-iteration-plateau`).

### 8.3 What I am NOT worried about

- The `risk_voice` prompt — it's threshold arithmetic dressed as an LLM
  call; even if gpt-4o-mini glitches, the contest-week ledger will
  surface it.
- The `memory_voice` prompt — it has a hard `≥3 matching rows`
  threshold and will return `abstain` whenever it can't ground a
  call. The worst failure mode is "memory_voice abstained too often",
  which the coordinator handles cleanly (Rule 3 only fires on a
  contradicting verdict; abstain passes).
- The coordinator — five lines of pinned Python. The PRD oracle's
  coordinator-in-prompt failures (S24 night-shift defer plateau) do
  not apply here because the local coordinator is not in a prompt.

The chart voice is the one. If the lab v0.1 fails, it fails on chart.

---

## 9. Report-back summary

- **Final v0.1 voice list (3 voices):**
  - `chart_analyst` — OHLCV setup grading; the reintroduction of the
    organ S24 WS-A deleted; sole positive-signal source.
  - `memory_voice` — last-20-decisions continuity check; novel
    surface, no PRD counterpart; the first piece of the
    compounding-evidence wedge.
  - `risk_voice` — bot's own breaker/PnL/budget state; hard veto on
    `bearish ≥ 0.8`; operational floor.
- **The literal coordinator rule set** (`coordinator.py`, ~5 lines):
  1. `risk == bearish AND risk.confidence >= 0.8` → `skip("risk_veto")`
  2. `chart != bullish OR chart.confidence < 0.6` →
     `skip("chart_below_threshold")`
  3. `memory == bearish AND memory.confidence >= 0.6` →
     `skip("memory_contradicts")`
  4. else → `act`. Confidence = `chart.confidence` on `act`;
     veto-voice confidence on `skip`.
- **The single voice prompt I am most worried about:** `chart_analyst`
  — it's the organ the PRD panel deletes by design; the abstain
  protocol is the only defense against the S24 confabulation failure;
  the thin-liquidity penalty clause is the load-bearing line and needs
  one targeted pre-contest probe (zero-vol synthetic bars) to confirm
  gpt-4o-mini honors it.
- **Subtlety the brief understated:** all three voices share ONE
  `MarketSnapshot` per turn, fetched once at the top of `open_position()`
  and passed by value. No voice refetches. This is non-obvious from
  the brief's "do voices share the same market_state snapshot, or does
  each fetch its own?" framing — the answer is shared-by-value-and-frozen,
  and it matters for replay determinism + cost + race-freeness. Pinned
  in §7.1.

---

## 10. Done-criteria for this spec

- [x] Voice list pinned (3 voices, with justifications for the two cuts).
- [x] `VoiceOpinion` / `LocalVoice` / `LocalDecision` contract locked.
- [x] Three voice prompts written literally (system + user + JSON shape).
- [x] Coordinator rule set written as code, not as prose.
- [x] Memory voice's `confirms / contradicts / novel` thresholds frozen.
- [x] Integration order with `gecko_wrap.py` pinned (between
      `_BREAKER.check()` and `_GATE.check_entry()`).
- [x] YAGNI cut list pinned (no embeddings, no outcomes, no PRD changes,
      no eval suite, no live X402, no prompt-loop sweep).
- [x] Single pre-contest probe budgeted (chart_analyst thin-liquidity
      synthetic).
- [x] Cost-ceiling math sanity-checked (~$0.30 over remaining contest
      window).

**Out-of-scope for this spec (handoff to software-engineer):** the
OpenRouter httpx client, the artifact ledger reader implementation,
the parallel `asyncio.gather` voice runner, the integration patch to
`jto_breakout_gecko_gated_contest_bot.py:268`. Those are
implementation, not design.

**Next deliverable** (not this spec): the software-engineer's
implementation under `contest_bot/local_panel/` + a light-fakes test
file under `contest_bot/tests/test_local_panel.py`. Per
`feedback-lighter-tests`, prefer pure-helper tests + `model_construct`
fixtures over end-to-end mocks.
