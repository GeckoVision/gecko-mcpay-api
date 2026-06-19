# Agent integration — wire it into the pre-trade loop

Two ways to call it: the **MCP tool** (preferred when the Gecko MCP server is
connected) or **plain HTTP** (works anywhere, no key). Both return the same
verdict shape.

## Option A — MCP tool (`gecko_safety`)

If the Gecko MCP server is connected (`mcp.geckovision.tech`), the agent has a
`gecko_safety` tool. Call it with the mint; it returns the gate + blocks. This
is the lowest-friction path inside Claude Code / Codex / any MCP client.

```
gecko_safety(mint="<SPL_MINT>") -> { gate, information_mev, wash_risk?, rug_flags, ... }
```

## Option B — HTTP (keyless, universal)

`POST https://api.geckovision.tech/safety` with `{"mint": "..."}`. Use this in
SDK runtimes (SendAI Solana Agent Kit, ElizaOS, OKX OnchainOS, a bare bot).

## The pattern: gate before you sign

Put the check **before** the swap, never after.

**TypeScript (SendAI / generic agent)**
```ts
const GECKO = "https://api.geckovision.tech/safety";

async function gateMint(mint: string): Promise<"block" | "caution" | "ok" | "unknown"> {
  try {
    const r = await fetch(GECKO, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mint }),
      signal: AbortSignal.timeout(8000),
    });
    if (!r.ok) return "unknown";
    return (await r.json()).gate ?? "unknown";
  } catch {
    return "unknown"; // fail-OPEN: degrade, don't crash
  }
}

// before executing a buy:
const gate = await gateMint(targetMint);
if (gate === "block") return abort("Gecko blocked this token's market");
if (gate === "unknown") return abort("safety check unavailable — abstaining");
if (gate === "caution") await confirmWithUser();   // reduced size
// gate === "ok" -> proceed
```

**Python**
```python
import httpx

async def gate_mint(mint: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post("https://api.geckovision.tech/safety", json={"mint": mint})
        return r.json().get("gate", "unknown") if r.is_success else "unknown"
    except Exception:
        return "unknown"
```

## Operational notes

- **Cache** the verdict per mint for ~30s — the oracle pre-computes and the value
  is stable on that horizon; this keeps a high-frequency agent cheap and fast.
- **Timeout + fail-OPEN**: bound the call (≤8s) and map any failure to `unknown`,
  then degrade (abstain / ask). Never let the check crash the trade loop, and
  never let a timeout read as `ok`.
- **Free tier limits**: the `/safety` tier is free for reasonable use; if you're
  checking thousands of distinct mints/min, contact Gecko. The cache above keeps
  almost everyone well under any limit.
- **Decision receipts** (optional): for auditability, log the full verdict JSON
  alongside the trade you made — it's the "why" behind an approve/deny.

## What NOT to do

- Don't call it *after* signing — it's a pre-trade gate.
- Don't whitelist on a single `ok` forever — markets change; re-check on a TTL.
- Don't treat `unknown` as `ok` (see [interpreting-verdicts.md](interpreting-verdicts.md)).
