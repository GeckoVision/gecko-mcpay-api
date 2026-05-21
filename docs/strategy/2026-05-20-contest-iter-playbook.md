# Contest iter-playbook — 2026-05-20

**Window:** now → 2026-05-21 07:00 UTC-3 (~14h remaining).
**Mode:** paper until founder funds + flips `PAPER_TRADE = False`.
**Discipline:** one knob per iteration. No multi-param changes mid-flight.

This playbook is the operational rulebook for the contest window. If
something doesn't fit one of the patterns below, **don't restart** —
write the observation in the journal and wait for clearer signal.

---

## The reboot drill (target ≤30s, no missed signal)

```bash
cd contest_bot
# ⚠️ kill ALL bot processes (not just the bash wrapper) — nohup leaks the python child
pgrep -f jto_breakout | xargs -r kill
sleep 2
pgrep -f jto_breakout || echo "(clear)"  # verify gone
ss -tlnp | grep 8265 || echo "(port free)"  # verify port released

set -a; . ../.env; set +a    # source OPENROUTER_API_KEY

# LIVE mode needs CONFIRM piped on stdin (interactive input() blocks nohup)
nohup bash -c 'echo CONFIRM | python3 -u jto_breakout_gecko_gated_contest_bot.py' > bot_live.log 2>&1 &
echo "PID: $!"
sleep 20
pgrep -f jto_breakout  # should show bash + python child
```

**Why `pgrep | xargs kill` not `kill <pid>`:** `nohup bash -c '...python3...'` spawns a bash wrapper that forks a python child. Killing the wrapper PID leaves the python orphan, which keeps port 8265 bound and crashes the next restart with `Address already in use`. Always sweep by name.

**What survives the reboot:**

- Open positions → `bot_state.json` (atomic write)
- Daily trade counter → `bot_state.json`
- Realized PnL + W/L counters → `bot_state.json` (added iter-3.x)
- Voice memory → `local_memory.jsonl` (append-only)
- Decision log → `artifact_YYYYMMDD.jsonl` (append-only)
- Circuit breaker state → `circuit_breaker_state.json`

**What does NOT survive:**

- In-session candidate scan cache (cold reset; takes ~30s to repopulate)
- Per-instrument last-snapshot cache (next poll refills)
- The dashboard "Signal Feed" tile (in-memory only)

None of these matter for trading correctness — they're cosmetic / cache.

---

## Iter-cycle decision table

Trigger fires when a position resolves (TP / SL / trail / time-stop / circuit-breaker).
Diagnose what fired, then apply ONE param change.

| Trigger | Diagnose | Apply |
|---|---|---|
| **TP hit** (+8%) | momentum thesis confirmed | size up: `USD_PER_TRADE` $50 → $75 |
| **SL hit** (-3%) | breakout was fake / entry too early | tighten chart floor: `_CHART_MIN_CONFIDENCE` 0.85 → 0.90 |
| **Trail-stop +5%** | trail did its job (we let winner run) | leave config, **no change**, repeat |
| **Trail-stop <+5%** | trail fired before activation gate — bug or noise | drop `TRAIL_ACTIVATE_AFTER_PCT` 5 → 3 |
| **Time-stop (12h)** | regime too quiet — no real move materialized | shrink `TAKE_PROFIT_PCT` 8 → 6 (faster realization) |
| **Circuit-breaker trip** | drawdown alarm — voices missed it | restart cleanly, no config change; investigate offline |

**Hard rule:** if the trigger doesn't fit the table, **do nothing**.
Founder's `feedback_prompt_iteration_plateau` rule applies — coordinator
logic stays in CODE. Tuning more than one knob per cycle is how you
chase noise.

---

## Three pre-staged iter-3.x variants

When BONK (or whichever position is open) resolves, decide between these
three based on what just happened.

### iter-3.1 SELECTIVE (post-SL or fake breakout)

**Hypothesis:** chart_analyst is letting through too-noisy setups; tighter
floor will improve win rate at the cost of fewer entries.

```python
# contest_bot/voices/coordinator_rules.py
_CHART_MIN_CONFIDENCE = 0.90  # was 0.85
```

Expected outcome: ~30-50% fewer candidates clear the gate; per-entry
quality up. Useful if SL hit cleanly + momentum thesis was wrong.

### iter-3.2 PERMISSIVE (post-long-quiet — no candidates fire for 4h+)

**Hypothesis:** BTC overlay + 0.85 floor are stacking — relax the
coarse safety belt and let voices be the sole gate.

```python
# contest_bot/jto_breakout_gecko_gated_contest_bot.py
BTC_OVERLAY = None  # was {"condition": "green_candle", ...}
# OR
_CHART_MIN_CONFIDENCE = 0.80  # was 0.85 — increase candidate volume
```

Pick ONE of the two, not both. Useful if the contest window is closing
and we have no realized trades.

### iter-3.3 FAST (post-time-stop or extended chop)

**Hypothesis:** market regime won't give us +8%; take the smaller
realized win and turn over capital faster.

```python
TAKE_PROFIT_PCT = 5            # was 8
TRAIL_ACTIVATE_AFTER_PCT = 3   # was 5
```

Expected outcome: more closes at +5% (or trail at +3-5%), fewer time-stops.
Trade-off: caps upside, but realized > unrealized when the clock is short.

---

## Things we will NOT change during the contest

- ❌ Add new instruments mid-flight (concentration > diversification with 1 slot)
- ❌ Disable any voice (chart / risk / memory — wedge stays intact)
- ❌ Switch from breakout/volume_spike to oversold-bounce (per quant: -EV on memes)
- ❌ Increase `MAX_DAILY_TRADES` above 3 (variance budget)
- ❌ Modify chart_analyst's MOMENTUM ACCELERATION lens (was the iter-2 wedge)
- ❌ Touch the X402 stub flag (paper-mode discipline)

---

## When to stop tuning

- Realized PnL ≥ +5% → leave config alone, ride
- Realized PnL ≤ -3% → stop trading for the day, manual review only
- 3 SL hits in a row → halt, investigate (do not just tighten)
- BTC moves >3% in either direction → wait one full poll cycle before deciding
- Less than 60min to contest close → no more config changes, let positions resolve

---

## Journal pattern (one line per iteration)

Append to `docs/strategy/2026-05-20-autonomous-overnight-journal.md`:

```markdown
### iter-3.<N> — <UTC time> — <trigger event>

- **Saw:** <one sentence: what closed, what fired, what didn't>
- **Hypothesis:** <one sentence: why we think the param change matters>
- **Changed:** <single key=value diff>
- **Restart:** PID <new pid>, state recovered: <position count>
```

That's it. No long debate, no multi-param post-mortems. One sentence
per slot, archived, move on.
