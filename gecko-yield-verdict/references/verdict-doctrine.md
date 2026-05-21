# Verdict Doctrine — how the Gecko panel decides, and why it abstains

This file explains what the `gecko_trade_research` verdict envelope means
so the skill renders it honestly. Load it when the user asks "how does the
verdict work" or when you need to interpret an unusual envelope.

## The 7-voice adversarial panel

A yield-deposit decision is not graded by one model. The Gecko oracle runs
a structured adversarial debate across seven distinct investor voices,
each grounded in public-domain / free-license investor literature. They do
not agree by construction — the verdict is what survives the argument.

| Voice | Lens it argues from |
|---|---|
| **Cycle / risk** (Howard Marks) | Where are we in the cycle? Is this yield paying for a risk nobody is pricing? "You can't predict, you can prepare." |
| **Valuation / risk premia** (Aswath Damodaran) | What discount rate does this yield imply? Is the premium compensation for default / depeg / smart-contract risk? |
| **Margin of safety** (Benjamin Graham) | Is there a buffer if the thesis is wrong? Mr. Market is offering this APY — why? |
| **Base rates / expectations** (Michael Mauboussin) | What is the base rate for pools at this APY surviving 90 days? Is the inside view overriding the outside view? |
| **Reflexivity** (George Soros) | Is the APY itself attracting the TVL that sustains the APY — a self-reinforcing loop that reverses hard? |
| **Tail risk** (Nassim Taleb) | What is the worst case? Is the downside bounded? A pool can pay 8% for a year then go to zero. |
| **Quality / compounding** (Berkshire letters) | Is the underlying protocol a durable franchise, or a yield farm with a roadmap? Would you hold this for years? |

The panel debates, voices dissent, and a synthesis step produces the final
verdict. The envelope does NOT carry a single "surviving dissent" string
(that field was never built). Dissent surfaces two ways: the integer
`dissent_count` (how many of the five non-debater analysts pointed the
other way) and the full per-voice transcript in `turns[]`. To render a
dissent line, lift one opposing analyst's closing sentence from `turns[]`
— see "What dissent looks like in the envelope" below.

## Verdict values

| Verdict | Meaning |
|---|---|
| **act** | The panel's grounded read supports the deposit. Citations back it. |
| **pass** | Inconclusive-to-negative — the case for depositing is not strong enough. NOT a hard block; the user may still proceed. |
| **defer** | The panel could not reach a confident call — usually because the corpus has no basis for *this* pool, or the inputs were too thin. Treat as "insufficient grounding", not "safe". |

`confidence` is a 0–1 number. Render it as-is. Low confidence on an `act`
verdict is itself a signal — say so, do not round it up.

## What dissent looks like in the envelope

In a normal panel, weaker arguments get answered and drop out. The
dissent that *still stands* after the debate is the objection that was
raised, argued, and not fully dismissed. A verdict of `act` with real
dissent is honest: the panel landed on yes, but here is the risk it could
not fully dismiss. Dissent without it is half the product — always
surface it next to the verdict.

The envelope exposes dissent as **`dissent_count`** — an integer counting
how many of the five non-debater analyst voices (`technical_analyst`,
`sentiment_analyst`, `fundamental_analyst`, `risk_manager`, `strategist`)
pointed opposite the coordinator's verdict. There is **no top-level
`surviving_dissent` string**. To render a concrete dissent line:

1. Read `dissent_count`. If `0`, state "no analyst voice dissented".
2. If `> 0`, scan `turns[]` for a non-coordinator analyst whose
   `parsed_verdict` opposes the coordinator's `verdict`, and quote one
   closing sentence from that turn's `content`.

A turn is `{agent, content, parsed_verdict}`; the coordinator's turn is
always last.

## What "abstain" means — the differentiator

The Gecko panel **abstains rather than fabricates.** If the investor-canon
corpus contains no basis for a confident statement about a pool, the panel
returns a `defer` verdict with empty `key_drivers` and empty citation
lists (`evidence_citations` + `framework_context`, or a legacy empty
`citations[]`) — it does **not** invent an APY threshold, a risk score,
or a fake citation to look decisive.

This is the proven differentiator: the S37 statistical ship-gate
(N=57) verified the panel hits a 6/6 honesty score — it does not
hallucinate numbers or sources. Every other paid agent races to sound
confident; Gecko's edge is that it tells you when it does not know.

When you render an abstain, say it plainly:
> *"The panel found no canon basis for a confident call on this pool — it
> abstained. Treat this as 'insufficient grounding', not 'safe'."*

Never reframe an abstain as a soft yes or a soft no. Abstain is a verdict.

## Reading citations

> **Verified S38-#130.** A citation item is
> `{id, source, url, chunk_id, provider_kind, freshness_tier, snippet}`.
> It does **not** carry `author`, `work`, or `locator` — those were
> fabricated in the pre-S38 skill draft. Confirmed against `Citation` in
> `gecko-core/orchestration/trade_panel/models.py` and a live probe.

The verdict splits citations into two lists (post-S35-#99 code):

- **`evidence_citations`** — "the data". Protocol/market chunks a panel
  turn referenced (e.g. `provider_kind` of `protocol_native`,
  `bazaar_live`, `paysh_live`, `market_data`).
- **`framework_context`** — "the lens". Investor-canon chunks the panel
  reasoned over (`provider_kind` of `canon_*`).

The deployed API may still emit a single legacy `citations[]` list (same
item shape) — merge whichever lists are present. Citations are the audit
trail; render them verbatim. Rules:

- Render each as `[{provider_kind}] {source} — {snippet} ({url})`.
- **Never add a citation the envelope did not return.** If the merged
  list is empty, render "no citations — see abstain note", not a guess.
- **Never alter the `snippet` or `url`.** Trim the snippet for length
  only; do not paraphrase it.
- The canon corpus is free + public-domain only in v0.1: Howard Marks
  (Oaktree memos), Aswath Damodaran (NYU Stern materials), Berkshire
  Hathaway shareholder letters — these surface as `canon_*` provider
  kinds in `framework_context`.

## Grounded, not fabricated — the principle

The skill's contract with the user: every number and every named source in
a Gecko-mode verdict traces to either (a) an onchainOS data call or (b) an
investor-canon citation in the envelope. Nothing is invented to fill a gap.
If you cannot ground a claim, the honest output is the abstain — that is
the product working as designed, not failing.
