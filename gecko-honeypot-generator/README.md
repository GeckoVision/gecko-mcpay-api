# gecko-honeypot-generator

Adversarial-input generator for crypto trading agents. Built for the Bento Guard partnership: Gecko generates the attacks, Bento Guard blocks them.

## What it does

For every legitimate `(symbol, mint)` pair in your agent's universe, generate **112+ adversarial variants** across 5 attack classes:

| Class | Count per token | Example | Severity |
|---|---|---|---|
| **typo** | ~10 | `PYTH` → `PPYTH`, `PYTH-`, `PYIH` | Medium |
| **unicode lookalike** | ~5 | `PYTH` → `РYTH` (Cyrillic Р, U+0420) | High |
| **hidden char** | ~10 | `PYTH` → `PY​TH` (zero-width space) | Medium |
| **mint substitution** | 3 | symbol=PYTH, mint=`<attacker addr>` | **CRITICAL** |
| **contract honeypot** | 10 | `FAKE-PYTH-sell_disabled` w/ devnet honeypot mint | Critical |

## Quickstart

```bash
git clone https://github.com/ernanibmurtinho/gecko-mcpay-api.git
cd gecko-mcpay-api/gecko-honeypot-generator
python3 honeypot_generator.py
```

Output: stdout report + `adversarial_corpus.json` (consumable by Bento Guard SDK).

## On-the-shelf result (PYTH/WIF/RAY universe)

```
Total adversarial inputs generated: 112

Current bot check (simulated):
  CAUGHT:    103  (92.0%)   ← hardcoded INSTRUMENTS allowlist catches typo/unicode/hidden-char
  BYPASSED:  9  (8.0%)      ← ALL mint-substitution; Bento Guard's pre-flight TX sim catches these
```

The 8% bypass rate is **the partnership's empirical claim**: Gecko's allowlist + Bento Guard's pre-flight = 0% bypass.

## Schema (per adversarial input)

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

## Adding a new attack class

1. Define a generator function `gen_<class>(symbol, mint) -> list[AdversarialInput]`
2. Add to `generate_corpus()` composite
3. Re-run `python3 honeypot_generator.py` — corpus expands automatically
4. Pipe to your SDK's test harness

## License

MIT. Built for joint use with Bento Guard. Forks and competitors welcome — adversarial-test corpus IS the test, not the secret.
