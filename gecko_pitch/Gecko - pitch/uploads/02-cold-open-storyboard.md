# Cold Open Storyboard — 0:00 to 0:15

**The hardest 15 seconds of the entire pitch.** This is what decides whether judges keep watching. Storyboarded frame-by-frame so the editor (or you) can shoot it once and not redo.

---

## Why this opens cold (no logo, no title)

A title card at 0:00 says "this is a pitch, here's the brand." A judge watching their 47th video tabs away. **Action says "this is happening, look at this." A judge stops scrolling.**

The trade-off: 15 seconds without your brand on screen feels scary. Trust it. Brand goes at the end card. By then they've watched you. Brand recognition lives in the memory of *what they saw*, not in seeing your logo upfront.

---

## Frame-by-frame

### Frame 1 — 0:00 to 0:01 (1 sec)
**On screen:** Pure black.
**Audio:** Silent.
**Purpose:** Reset the viewer. They were just on another video. This is the hard cut.

### Frame 2 — 0:01 to 0:04 (3 sec)
**On screen:** Cut to terminal. Claude Code session, dark theme. Cursor at prompt.

The user begins typing — characters appearing in real time:

```
Use gecko_research to validate: a hotel guide for Brazil
```

**Audio:** Faint keystroke sounds. (Real keystrokes, not generic clicks. Record from a real keyboard.)
**Purpose:** Establish "agent receiving a task." The viewer reads as it's typed. They're now mentally inside the moment.

### Frame 3 — 0:04 to 0:07 (3 sec)
**On screen:** Below the prompt, output appears in real time:

```
→ POST https://api.geckovision.tech/research

← HTTP 402 Payment Required
  Required: $20.00 USDC
  Network: Solana
  Pay to:  9xK7d4h2...3pQrM8
```

The "402" should be color-highlighted (red or orange — make it pop) so the viewer's eye catches it.

**Audio:** Silent except faint terminal beep on the 402.
**Purpose:** The agent hit a paywall. Anyone who knows what 402 means is now leaning in.

### Frame 4 — 0:07 to 0:10 (3 sec)
**On screen:** Split-screen wipe. Left half: terminal. Right half: a browser tab on `solana.fm` or `explorer.solana.com`.

**Left (terminal):**
```
→ Signing payment via frames.ag wallet...
→ Transaction broadcast: 5xA8mNp2...
→ Awaiting confirmation...
→ Confirmed (slot 312,884,401)
```

**Right (browser):** Solana Explorer page actively loading. The transaction appears: "USDC Transfer — 20.00 USDC — Confirmed [seconds ago]." Pay attention to making this look real — show the actual cluster, the actual block height.

**Audio:** Quiet keyboard sound, then a single soft "confirmation" beep when the explorer updates.
**Purpose:** Real money moved. The viewer just watched an autonomous payment. This is the *moment.*

### Frame 5 — 0:10 to 0:12 (2 sec)
**On screen:** Wipe back to fullscreen terminal.

```
→ Indexing 7 sources... [████████] complete
→ Generating documents...
```

The progress bar fills smoothly. (If you record this live and it's too slow, speed up — judges don't care about real ingestion time, they care about visible progress.)

**Audio:** Silent.
**Purpose:** Bridge from payment to product. "The thing they paid for is happening."

### Frame 6 — 0:12 to 0:13 (1 sec)
**On screen:** First Rich panel renders. Visible long enough to read the title and a line of content:

```
┌─ Business Plan ──────────────────────────┐
│                                            │
│  Problem: Brazilian travelers booking      │
│  hotels rely on global aggregators that... │
│                                            │
│  [more content visible but not focal]      │
│                                            │
│  Sources: ▲ youtube.com/watch?v=...        │
└────────────────────────────────────────────┘
```

**Purpose:** "Documents arrived." Don't show all three panels — just the first, framed enough to convey there's structured content with citations.

### Frame 7 — 0:13 to 0:15 (2 sec)
**On screen:** Black background. White text, centered, large enough to read at any video size:

> *An AI agent just paid for its founder*
> *to find out if their idea is real.*

**Audio:** Silent.
**Purpose:** Name the moment they just witnessed. *"Just"* and *"founder"* are deliberate — they make it human.

**Hold 2 full seconds. Don't rush off this card.** This is the moment that earns the next 2:45 of attention.

---

## What can go wrong, and how to avoid it

| Risk | Mitigation |
|---|---|
| Terminal text too small to read | Use 18pt minimum font in the terminal. Test by playing the video back at the size a judge would watch (probably mobile or laptop). |
| Solana Explorer link looks fake | Use a real transaction. Even on devnet — judges aren't checking the cluster, but they ARE checking that the explorer UI looks real. Don't mock this up in Figma. |
| Whole sequence feels rushed | If 15 seconds isn't enough to land it, take 18. Don't take 25 — you steal time from the rest of the pitch. |
| Whole sequence feels slow | Cut Frame 1 to 0.5 sec. Cut Frame 6 to be tighter on the panel. Reclaim 1-2 seconds. |
| Captions distract from the action | Burn captions only on Frame 7 ("An AI agent just paid..."). Don't caption the terminal output — the text on screen IS the caption. |
| Color highlighting on "402" looks tacky | Subtle. A slightly different terminal color is enough. Don't put a glowing red box around it. |

---

## The single hardest thing to get right

**The transaction confirmation has to feel like it's happening, not like it already happened.** The risk of recording this is making it look pre-baked.

Fix: record the actual `gecko-mcp` call, in real time, on a real wallet, against the real `gecko-api`. Don't fake any part of it. If the real flow takes 12 seconds and you only have 6, that's fine — speed up the playback in editing. But the underlying capture needs to be a real transaction with a real signature you can link to.

When a judge clicks the link in your video description and the transaction is *actually there*, you've passed the trust test that 90% of hackathon pitches fail.

---

## Recording checklist

- [ ] Real frames.ag wallet funded with USDC on Solana mainnet (not devnet — mainnet is more credible)
- [ ] Real `gecko-api` deployed and reachable
- [ ] Capture screen at 1080p, 60fps if possible (smoother text rendering)
- [ ] Capture audio separately if you need keyboard sounds — most screen recorders make terminal keystrokes sound fake
- [ ] Multiple takes — you'll re-record this 5-10 times before it's right. Budget the time.
- [ ] Save the transaction signature. Put the explorer link in the video description.
