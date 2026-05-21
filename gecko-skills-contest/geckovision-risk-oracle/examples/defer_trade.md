# Example: DEFER Trade

## Scenario
A user is using the OKX Agentic Wallet and discovers a new DeFi token that looks promising. They ask their agent to check if it's safe to trade.

## User Input
```
"Should I buy 1000 USDC worth of NEWFI on Solana?"
```

## Agent Workflow

### Step 1: Trigger Detection
The agent detects the trade intent and invokes the GeckoVision Risk Oracle skill.

### Step 2: Data Gathering
The agent uses OnchainOS skills to gather data:

**okx-dex-token (NEWFI):**
```json
{
  "token": "NEWFI",
  "address": "7xKXtg2CW87d98KYvYixYaZznhKQQeKQYWEiPjMXQQs",
  "chain": "solana",
  "market_cap": "$5M",
  "liquidity": "$500k",
  "verified_contract": false,
  "audit_status": "Pending",
  "age": "5 days",
  "holder_concentration": "45% in top 10"
}
```

**okx-dex-market (NEWFI):**
```json
{
  "price": "$0.50",
  "volume_24h": "$100k",
  "volatility": "15%",
  "slippage": "2.5%"
}
```

**okx-wallet-portfolio (User):**
```json
{
  "total_balance": "$10,000",
  "holdings": {
    "SOL": "$2,000 (20%)",
    "USDC": "$5,000 (50%)",
    "ETH": "$2,000 (20%)",
    "Other": "$1,000 (10%)"
  }
}
```

**okx-security (NEWFI):**
```json
{
  "contract_verified": false,
  "audit_status": "Pending",
  "phishing_detected": false,
  "risk_score": 6
}
```

### Step 3: Three-lens panel
- **🟦 Market-structure lens** → `neutral @ 0.5` — liquidity $500k is shallow, volatility 15%; not a clean confirmed setup, not broken either
- **🟥 Security lens** → `neutral @ 0.6` — no honeypot/phishing (no veto), but contract unverified (audit pending) — unresolved, not disqualifying
- **🟩 Portfolio-memory lens** → `neutral @ 0.6` — 10% portfolio impact acceptable; holder concentration 45% noted

**Coordinator:** rule 1 (security veto) does not fire — security is neutral,
not bearish@≥0.8. Rule 2 fires — market is **not bullish** (neutral @ 0.5),
so the panel has no affirmative green light → **DEFER /
insufficient_positive_signal**. The trade isn't a scam; it just hasn't
earned a SAFE.

### Step 4: Output
```json
{
  "verdict": "DEFER",
  "confidence_score": 55,
  "coordinator_reason": "insufficient_positive_signal",
  "lenses": {
    "market":   {"verdict": "neutral", "confidence": 0.5, "observations": ["liquidity $500k — shallow", "volatility 15%"]},
    "security": {"verdict": "neutral", "confidence": 0.6, "observations": ["contract unverified — audit pending", "no honeypot/phishing"]},
    "memory":   {"verdict": "neutral", "confidence": 0.6, "observations": ["10% portfolio impact — acceptable", "holder top10 45%"]}
  },
  "surviving_dissent": [
    "Contract unverified — not a veto, but unresolved",
    "Holder concentration 45% in top 10",
    "High volatility (15%)"
  ],
  "reasoning": "NEWFI is not a scam — the security lens finds no honeypot or phishing. But the market lens cannot confirm a clean tradeable structure (shallow liquidity, high volatility), so no lens reaches a green-light bar. The oracle abstains rather than fabricate a SAFE.",
  "recommendation": "Verify the contract on a block explorer and reduce size by 50% before proceeding — or wait for the audit.",
  "citations": [
    "okx-security: contract_verified=false, audit_status=pending",
    "okx-dex-token: holder_concentration=45%",
    "okx-dex-market: liquidity=$500k, volatility=15%",
    "canon: Marks — reward thin liquidity with suspicion, not optimism"
  ]
}
```

### Step 5: User Confirmation
The agent receives the DEFER verdict and asks the user for explicit confirmation:

```
Agent: "Risk check returned DEFER. This token has moderate risk factors:"
Agent: "  - Unverified contract (audit pending)"
Agent: "  - High holder concentration (45% in top 10)"
Agent: "  - High volatility (15%)"
Agent: ""
Agent: "Recommendation: Reduce trade size by 50% or wait for contract audit."
Agent: ""
Agent: "Do you want to proceed with the full trade, reduce the size, or skip?"
```

## Possible User Responses

### Option 1: Proceed with Full Trade
```
User: "Proceed with the full 1000 USDC trade"
Agent: "Confirmed. Proceeding with full trade at user's risk."
Agent: "Executing swap: 1000 USDC → ~2000 NEWFI"
Agent: "Trade executed. Risk verdict logged for audit trail."
```

### Option 2: Reduce Trade Size
```
User: "Reduce to 500 USDC"
Agent: "Confirmed. Reducing trade size to 500 USDC."
Agent: "Executing swap: 500 USDC → ~1000 NEWFI"
Agent: "Trade executed with reduced exposure."
```

### Option 3: Skip Trade
```
User: "Skip this trade"
Agent: "Trade cancelled. Waiting for next instruction."
```

## Key Takeaways
- **Cautious:** The verdict flags moderate risks but doesn't block the trade.
- **Transparent:** The user understands exactly why the verdict is DEFER.
- **User Agency:** The user retains control and can override the verdict if they choose.
- **Audit Trail:** All decisions and overrides are logged for compliance.
