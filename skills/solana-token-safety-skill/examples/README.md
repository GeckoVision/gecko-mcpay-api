# Example verdicts

Reference `/safety` responses so you can see the shape and the two ends of the
spectrum before wiring anything.

| file | token | gate | why |
|---|---|---|---|
| [`clean-jup.json`](clean-jup.json) | JUP (Jupiter) | `ok` | deep liquidity, no manipulation flags — a real, established market. **Real capture (2026-06-19).** |
| [`blocked-brca.json`](blocked-brca.json) | BrCA-style | `block` | $5.73M headline mcap on $6.5K liquidity, 72% single-holder, bot buy-loop + price bait. **Illustrative** (documented case; shape matches live, values reflect the case). |

The contrast is the whole point: the blocked token is exactly the kind a contract
checker passes (the *contract* is fine) while its **market is manufactured** —
which is what this skill catches.

Reproduce the clean one yourself:

```bash
curl -s -X POST https://api.geckovision.tech/safety \
  -H "Content-Type: application/json" \
  -d '{"mint":"JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}'
```
