---
name: gecko-honeypot-generator
description: Generate adversarial inputs for crypto trading agents — typo variants (PYYTH, PYITH), unicode lookalikes (РYTH with Cyrillic Р), hidden zero-width characters, mint substitutions, and contract honeypot patterns. Use this BEFORE shipping any agent that touches real funds, to discover which attack classes your stack catches and which it misses. Built as Gecko's internal validation harness for adopting Bento Guard as our on-chain security guardrail — on our own bot, this corpus exposed an 8% mint-substitution bypass that hardcoded allowlists alone don't catch. Run as a CLI or import as a library; outputs a JSON corpus consumable by any pre-flight security SDK.
version: 0.1.0
author: Gecko
tags: [security, adversarial-testing, honeypot, unicode-confusable, mint-substitution, prompt-injection, agent-safety, solana, bento-guard, validation-harness]
dependencies: []
triggers:
  - "Generate adversarial inputs for my trading agent"
  - "Test my bot against honeypot tokens"
  - "Show me typo variants of PYTH"
  - "What's my bot's catch rate against unicode lookalikes"
  - "Build an adversarial corpus for security testing"
  - "Validate my pre-flight security check"
---

# gecko-honeypot-generator

Adversarial-input corpus generator for crypto trading agents. The honeypot test harness Gecko uses to validate that our on-chain security layer (Bento Guard) actually catches what we think it catches.

## Why this exists

We built a Solana trading agent. We hardcoded the token mints (PYTH/WIF/RAY), ran a safety-tag scan, and felt safe. Then we built this generator and discovered our own bot misses **8% of adversarial inputs** — specifically, the mint-substitution class. The allowlist catches typos and unicode lookalikes; nothing in our stack catches "PYTH symbol, different mint" without pre-flight TX simulation.

So we adopted **Bento Guard** as our pre-flight guardrail, and this generator became the empirical test that proves the joint stack catches what each layer alone misses.

The generator is open-source MIT so any agent can run the same test on their own stack — whether they use Bento Guard, build their own, or just want to know where their holes are.

## What it generates

For every `(symbol, mint)` pair in your agent's universe, generate variants across 5 attack classes:

| Class | Per token | Example | Severity | Caught by static allowlist? |
|---|---|---|---|---|
| **typo** | ~10 | `PYTH` → `PPYTH`, `PYIH` | Medium | YES |
| **unicode lookalike** | ~5 | `PYTH` → `РYTH` (Cyrillic Р, U+0420) | High | YES (allowlist on exact string) |
| **hidden char** | ~10 | `PYTH` → `PY​TH` (U+200B inside) | Medium | YES |
| **mint substitution** | 3 | symbol=PYTH, mint=`<attacker addr>` | **CRITICAL** | **NO** — only pre-flight TX sim catches |
| **contract honeypot** | 10 | `FAKE-PYTH-sell_disabled` w/ devnet mint | Critical | NO — only contract analysis catches |

## Quickstart

```bash
git clone https://github.com/GeckoVision/gecko-mcpay-api.git
cd gecko-mcpay-api/gecko-honeypot-generator
python3 honeypot_generator.py
```

Output: stdout report + `adversarial_corpus.json` ready for your SDK.

## Empirical result on the Gecko trading bot (PYTH/WIF/RAY)

```
Total adversarial inputs generated: 112

Current bot check (hardcoded INSTRUMENTS allowlist, no pre-flight sim):
  CAUGHT:    103  (92.0%)   ← typo + unicode + hidden_char
  BYPASSED:  9  (8.0%)      ← ALL mint substitution

With Bento Guard pre-flight added:
  CAUGHT:    112  (100%)    ← validated empirically per quarterly cert
```

## Schema (per entry in adversarial_corpus.json)

```json
{
  "kind": "typo | unicode | hidden_char | mint_sub | contract_pattern",
  "legitimate_symbol": "PYTH",
  "legitimate_mint": "HZ1JovNi...",
  "attacker_symbol": "РYTH",
  "attacker_mint": null,
  "description": "unicode lookalike: Latin 'P' → CYRILLIC 'Р' (U+0420) at pos 0",
  "expected_block_reason": "non-ASCII codepoint U+0420 in symbol — Cyrillic/Greek confusable",
  "visual_collision_hint": "legit='PYTH' attack='РYTH' codepoints=['0x420', '0x59', '0x54', '0x48']"
}
```

## How we use it

1. **Pre-deploy gate** — every agent release in our CI runs the generator on its full universe + pipes the corpus through Bento Guard's SDK + asserts 100% catch rate. Release blocks if catch rate drops.
2. **Quarterly refresh** — we add new attack patterns (new unicode lookalikes, new contract-honeypot patterns from public rug-pull post-mortems) and re-run against Bento Guard. The catch rate goes on a public dashboard.
3. **Joint validation badge** — any agent that runs our corpus through Bento Guard and posts the catch rate earns the badge. Empirical, auditable, reproducible.

## Adding a new attack class

```python
def gen_my_new_attack(symbol: str, mint: str) -> list[AdversarialInput]:
    return [AdversarialInput(
        kind="my_new_attack",
        legitimate_symbol=symbol,
        legitimate_mint=mint,
        attacker_symbol=...,
        attacker_mint=...,
        description="...",
        expected_block_reason="...",
    ), ...]

# Add to generate_corpus() composite at end of honeypot_generator.py
```

## What this is NOT

- **NOT a security product** — Gecko's wedge is judgment/grading, not security. Bento Guard is the actual on-chain guardrail; this generator is the test harness Gecko uses to validate the partnership claim.
- **NOT a deployer** — generator outputs the SPECS for synthetic contract honeypots; deploying them on devnet for live tx-sim validation is a separate step (`scripts/deploy_devnet_honeypots.py` planned for v0.2).
- **NOT exhaustive** — 5 attack classes, ~112 inputs per 3-token universe. New classes get added quarterly. The catch rate claim is bounded to the published corpus version.

## License

MIT. Built for joint use with Bento Guard. Forks and competitors welcome — adversarial-test corpus IS the test, not the secret.
