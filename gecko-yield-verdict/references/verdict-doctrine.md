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
verdict. **One dissent line survives into the envelope** — the single
strongest counter-argument the verdict had to overcome. That line is not
decoration; render it.

## Verdict values

| Verdict | Meaning |
|---|---|
| **act** | The panel's grounded read supports the deposit. Citations back it. |
| **pass** | Inconclusive-to-negative — the case for depositing is not strong enough. NOT a hard block; the user may still proceed. |
| **defer** | The panel could not reach a confident call — usually because the corpus has no basis for *this* pool, or the inputs were too thin. Treat as "insufficient grounding", not "safe". |

`confidence` is a 0–1 number. Render it as-is. Low confidence on an `act`
verdict is itself a signal — say so, do not round it up.

## What "surviving dissent" means

In a normal panel, weaker arguments get answered and drop out. The
*surviving* dissent is the objection that was raised, argued, and **still
stands** after the debate. A verdict of `act` with a sharp surviving
dissent is honest: the panel landed on yes, but here is the real risk it
could not fully dismiss. Always render the surviving-dissent line next to
the verdict — a verdict without its dissent is half the product.

## What "abstain" means — the differentiator

The Gecko panel **abstains rather than fabricates.** If the investor-canon
corpus contains no basis for a confident statement about a pool, the panel
returns a `defer` verdict and citations that are empty or explicitly note
"no figure in corpus" — it does **not** invent an APY threshold, a risk
score, or a fake citation to look decisive.

This is the proven differentiator: the S37 statistical ship-gate
(N=57) verified the panel hits a 6/6 honesty score — it does not
hallucinate numbers or sources. Every other paid agent races to sound
confident; Gecko's edge is that it tells you when it does not know.

When you render an abstain, say it plainly:
> *"The panel found no canon basis for a confident call on this pool — it
> abstained. Treat this as 'insufficient grounding', not 'safe'."*

Never reframe an abstain as a soft yes or a soft no. Abstain is a verdict.

## Reading citations

Each citation carries `author`, `work`, and a `locator` (memo date,
chapter, page). Citations are the audit trail — they let the user check
the reasoning against the source. Render them verbatim. Rules:

- **Never add a citation the envelope did not return.** If `citations` is
  empty, render "no canon citations — see abstain note", not a guess.
- **Never alter a locator.** If the oracle says "memo 2006-01", render
  exactly that. Do not "improve" it to a page number.
- The corpus is free + public-domain only in v0.1: Howard Marks (Oaktree
  memos), Aswath Damodaran (NYU Stern materials), Berkshire Hathaway
  shareholder letters. A citation outside this set in a v0.1 envelope is a
  bug — surface it, do not hide it.

## Grounded, not fabricated — the principle

The skill's contract with the user: every number and every named source in
a Gecko-mode verdict traces to either (a) an onchainOS data call or (b) an
investor-canon citation in the envelope. Nothing is invented to fill a gap.
If you cannot ground a claim, the honest output is the abstain — that is
the product working as designed, not failing.
