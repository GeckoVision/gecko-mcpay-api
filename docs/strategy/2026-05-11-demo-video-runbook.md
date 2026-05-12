# Gecko — Colosseum demo video, recording runbook

> 90-second Loom + voice-over. Calibrated against the 34-judge corpus (see `2026-05-11-colosseum-demo-video-guide.md` for the framework). Read this on your phone while recording on your laptop.

---

## Pre-flight checklist (run ~10 min before recording)

```bash
# 1. Working directory + env
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
set -a; source .env; source .env.add; set +a

# 2. Confirm prod is healthy + new oracle client lights up
PROTOCOL=kamino VERTICAL=dex \
  QUESTION="Should a trader deposit USDC into the Kamino USDC reserve right now?" \
  GECKO_API=https://api.geckovision.tech \
  bash /tmp/gecko-test.sh
# expect 11/11 pass; if anything red, stop and diagnose

# 3. Clean Mongo orphans (keeps `ls` tidy for the deploy beat)
uv run bb trade-agent purge --status stopped --dry-run
uv run bb trade-agent purge --status stopped

# 4. Pre-warm a verdict in the cache so reverdict returns in ~5s
#    (the demo benefits from a fast cache-hit on the reverdict moment)
#    Use --tier pro to match the voice-over claim of "seven specialist voices"
#    (basic = 5 voices, pro = 7 voices).
uv run bb trade-agent reverdict <agent_id> --tier pro --dry-run  # this one's just to confirm the path works

# 5. Have the example spec file ready
cat /home/nan/.gecko/specs/example-kamino-dca.json | head -5
# expect: name=kamino-usdc-dca, protocol=kamino, vertical=dex

# 6. Open Solscan in a tab to one of our settled txs (for the visible-trust moment)
# https://solscan.io/tx/4FPSxDGJQykp3j5cbnkGjAd8DVebsHBmazLQNCfEFZ3okKrgWCQi81ujr7aJS8MEbHUDXPEqn7EMAVBdAxwUyWoY

# 7. Set terminal: large monospace font (16-18pt), no transparency, clean prompt.
#    Recommended: dark background, light text (universal readability).
```

**If anything fails in pre-flight, do not record.** A failed demo on judge airtime kills more than running yesterday's working version.

---

## Recording setup

- **Tool:** Loom (founder's choice), webcam on for the founder's face in a small corner
- **Screen:** Claude Code terminal full-screen + 1 side terminal for `ls` / `inspect` / `reverdict`
- **Microphone:** quiet room, no echo. Test by playing back the first 5 seconds before recording the full take
- **Aspect:** 16:9, 1080p minimum
- **Length target:** 90 seconds. Hard ceiling: 110 seconds.

---

## The script — exact words + exact actions

The script is timed. Each beat has: **what's on screen** (left), **what to say** (right), **the exact action you take** (italic, beneath).

### Beat 1 — title (0:00–0:05)

| screen | voice-over |
|---|---|
| Black slide, monospace, white text only: <br><br> **Gecko — strategy oracle for autonomous trading agents.** <br><br> *(below, smaller)* by Ernani | *(silence — let them read the line)* |

*Action:* full-screen title card for 5 seconds. No animation. No music yet.

### Beat 2 — hook (0:05–0:15)

| screen | voice-over |
|---|---|
| Cut to Claude Code, fresh chat. Cursor blinking in the input. | *"I'm Ernani — Brazilian dev. I lost money on my last three Solana trades because the LLM just told me what I wanted to hear. So I built the oracle my agent should have called instead."* |

*Action:* you've already typed *"Should I deposit USDC into the Kamino USDC reserve right now?"* before recording — paste it now, hit enter at 0:10. The verdict will fire while you finish the voice-over.

### Beat 3 — the wedge in motion (0:15–0:35)

| screen | voice-over |
|---|---|
| Verdict envelope renders in Claude Code. Scroll slowly through: <br>• `verdict: defer  confidence: 0.7` <br>• `dissent_count: 2` <br>• citation 1 = Damodaran "Equity Risk Premium" <br>• citation 2 = Howard Marks Oaktree memo | *"Seven specialist voices debated this question. Two disagreed with the verdict — the dissent survives on screen. Damodaran on the equity risk premium. Howard Marks on cycle position. Every citation links to the actual source — investor-canon, not LLM hallucination."* |

*Action:* hover the cursor over one citation URL so it's visibly highlighted. Don't click — keep the flow.

### Beat 4 — the chain proof (0:35–0:45)

| screen | voice-over |
|---|---|
| Quick cut to the Solscan tab. Show the settled tx page for: <br> `4FPSxDGJQykp3j5cbnkGjAd8DVebsHBmazLQNCfEFZ3okKrgWCQi81ujr7aJS8MEbHUDXPEqn7EMAVBdAxwUyWoY` <br> Highlight: *"Confirmed", "0.01 USDC", "Block height", "1.6 sec"* | *"Every paid call settles on Solana mainnet. This one — 25 cents — confirmed in 1.6 seconds. Real transaction. No API keys, no signup. You can verify it yourself on Solscan."* |

*Action:* cut back to Claude Code at 0:45.

### Beat 5 — the durable surface (0:45–1:05)

| screen | voice-over |
|---|---|
| Type in Claude Code: *"Deploy this strategy as a local advisor agent."* <br><br> Claude reads the gecko-trade-agent skill, runs `bb trade-agent up …` in background, returns an agent_id. <br><br> Cut to side terminal. Run: <br> `uv run bb trade-agent inspect <agent_id>` <br><br> Show: `status=running · mode=advisor · journal: agent_started + verdict_called` | *"Now the agent lives on my laptop. My keys. My journal. It checks the panel on a schedule, surfaces opportunities I'd miss, and never signs anything I haven't approved. Local-first, by design."* |

*Action:* the `inspect` output is the load-bearing screen here — pause on it for ~3 seconds so judges can read.

### Beat 6 — the moat claim (1:05–1:20)

| screen | voice-over |
|---|---|
| Stat strip overlay (text-only, monospace, lower-third): <br><br> `4,874 corpus chunks · 7 panel voices · 80 settled mainnet tx · $0.17 lifetime spend` | *"It's iterative — not a new category. Marketplaces like frames.ag and Bazaar sell directories of paid agents. None of them sell the verdict — they'd have to pick a side on every listing in their own catalog. The strategy oracle layer is structurally ours."* |

*Action:* let the stat strip sit for the full 15 seconds — viewers re-read it. Cut back to terminal at 1:20.

### Beat 7 — force of will (1:20–1:30)

| screen | voice-over |
|---|---|
| End card: <br><br> **`app.geckovision.tech`** <br><br> *(below, smaller)* <br> `curl -fsSL app.geckovision.tech/install.sh \| bash` <br><br> *(below, even smaller)* <br> `no API keys · just a wallet` | *"Yesterday I caught a retrieval bug that hid our entire 4,800-chunk corpus from the panel. Fixed it the right way — architectural cleanup, not a workaround. Validated in production smoke. That's founder mode. One curl command. No API keys. Find me at geckovision dot tech."* |

*Action:* hold the end card for the last 3-4 seconds.

---

## Total: 90 seconds.

Voice-over word count: ~195 words. At a calm 130 wpm = 90s.

---

## Backup plan for moments that could break

| If this breaks | Do this |
|---|---|
| Claude Code doesn't pick up the gecko-trade-coach skill | Cut to running `uv run python -c "..."` in the terminal that calls `gecko_trade_research` directly. Same envelope, slightly less chat-y. |
| The verdict takes >40s to return | Pre-cache a JSON file at `/tmp/gecko-pro.json` (already done from earlier today). If the live call drags, cut to `cat /tmp/gecko-pro.json \| jq`. Voice-over stays the same. |
| `bb trade-agent up` doesn't background cleanly in Claude Code | Switch to a side terminal that you `tmux attach -t gecko-agent` into (have a tmux session pre-started). Same payoff, no chat hang. |
| Solscan page lags | Have a Solscan screenshot saved at `/tmp/solscan-tx.png` and `xdg-open` it as a fallback. |
| Webcam/mic dropout | Stop recording, re-take. Don't ship a flawed take to "save time" — judges notice. |

---

## The artifacts on screen that earn judge points

From the demo video guide's 4-axis framework, here's what each beat hits:

| Beat | Axis served | Specifically |
|---|---|---|
| Title (0:00) | Gui — clarity in 5s | One-liner on screen, no narration over it |
| Hook (0:05) | Adam — specific user segment | "Brazilian dev, last 3 trades, GPT told me what I wanted to hear" |
| Wedge (0:15) | Adam + Qiao — PMF evidence + falsifiability | The verdict says `defer` (not always `act`); dissent visible |
| Chain proof (0:35) | Billy — brag with context | Mainnet tx hash, verifiable on Solscan |
| Durable surface (0:45) | Qiao + Gui — force of will + tech depth visible | Agent running locally, journal scrolling, no overdone aesthetic |
| Moat (1:05) | Adam + Billy — category position + market named | "Iterative", named incumbents, structural moat |
| Force of will (1:20) | Qiao — willingness to be wrong | The retrieval-bug story, named, with the fix shipped |
| End card (1:27) | Gui — actionable CTA | URL + one-line install |

Every beat earns at least one axis. The chain-proof beat (0:35) and the force-of-will beat (1:20) are the two highest-EV moments — those are where you go from "another submission" to "remembered submission."

---

## After recording — pre-publication checklist

- [ ] Watch the full 90s once with audio at 100%. Anything you wince at, re-shoot just that beat (Loom supports it).
- [ ] Confirm the title card is readable on a phone (judges watch on phones at 2 AM).
- [ ] Confirm the citation names are visible during beat 3 (zoom in if needed).
- [ ] Confirm the tx hash is partially readable during beat 4 (full hash unreadable is fine; the visible chars + "Confirmed" badge are the signal).
- [ ] Make sure your face cam is in a corner that doesn't cover any of the terminal content.
- [ ] Export at 1080p minimum.
- [ ] Title: *"Gecko — strategy oracle for autonomous trading agents (90s demo)"*
- [ ] Description: 2 sentences + the install one-liner.
- [ ] Pin one tweet quoting the chain-proof tx hash with the Solscan link. Anyone who clicks through verifies the demo is real.

---

## What NOT to do (judge-calibrated red flags)

- ❌ **Don't open with the founder bio slide.** Open with the user / problem.
- ❌ **Don't show a TAM number.** Adam reads this as airdrop-farming framing.
- ❌ **Don't use a gradient hero or animated background.** Gui penalizes overdone Web3 aesthetics on sight.
- ❌ **Don't promise features in voice-over that aren't on screen.** Every claim must be paired with a visible artifact.
- ❌ **Don't dodge the iterative-vs-greenfield framing.** Beat 6 names our position explicitly — that earns Adam's respect.
- ❌ **Don't add background music louder than -20dB.** A judge muting your video is the worst outcome.

---

## One-line close (for you, before you record)

The viewer is a tired judge on submission #41. They want a tx hash by second 35 and a contrarian claim by second 65. Everything else is decoration.
