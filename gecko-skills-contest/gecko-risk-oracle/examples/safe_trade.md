# Example: SAFE Trade

## Scenario
A user is using the OKX Agentic Wallet with the Gecko Risk Oracle skill installed. They want to buy Solana (SOL) using their agent.

## User Input
```
"Should I buy 1000 USDC worth of SOL on Solana?"
```

## Agent Workflow

### Step 1: Trigger Detection
The agent detects the trade intent and invokes the Gecko Risk Oracle skill.

### Step 2: Data Gathering
The agent uses OnchainOS skills to gather data:

**okx-dex-token (SOL):**
```json
{
  "token": "SOL",
  "address": "11111111111111111111111111111111",
  "chain": "solana",
  "market_cap": "$150B",
  "liquidity": "$500M+",
  "verified_contract": true,
  "age": "4 years",
  "holder_concentration": "8% in top 10"
}
```

**okx-dex-market (SOL):**
```json
{
  "price": "$180",
  "volume_24h": "$5B",
  "volatility": "2.5%",
  "slippage": "0.01%"
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

**okx-security (SOL):**
```json
{
  "contract_verified": true,
  "audit_status": "Passed",
  "phishing_detected": false,
  "risk_score": 1
}
```

### Step 3: Three-lens panel
Each lens analyzes the trade independently. They are allowed to disagree;
the coordinator turns their verdicts into a decision.

- **🟦 Market-structure lens** → `bullish @ 0.9` — liquidity $500M+, slippage 0.01%, deep clean structure
- **🟥 Security lens** → `neutral @ 0.7` — native asset, no contract attack surface, no flags
- **🟩 Portfolio-memory lens** → `neutral @ 0.6` — trade is ~5% of book, well within concentration limits

**Coordinator:** rule 1 (security veto) does not fire; rule 2 passes
(market bullish @ 0.9 ≥ 0.6); rule 3 does not fire (memory not bearish) →
**SAFE / all_lenses_aligned**

### Step 4: Output
```json
{
  "verdict": "SAFE",
  "confidence_score": 92,
  "coordinator_reason": "all_lenses_aligned",
  "lenses": {
    "market":   {"verdict": "bullish", "confidence": 0.9, "observations": ["liquidity $500M+", "slippage 0.01%"]},
    "security": {"verdict": "neutral", "confidence": 0.7, "observations": ["native asset, no contract risk"]},
    "memory":   {"verdict": "neutral", "confidence": 0.6, "observations": ["~5% of portfolio — within limits"]}
  },
  "surviving_dissent": [],
  "reasoning": "SOL has deep liquidity, no contract attack surface, and the trade is a small, well-diversified addition. All three lenses align.",
  "recommendation": "Proceed. Consider a limit order to minimize slippage.",
  "citations": [
    "okx-dex-market: liquidity=$500M+, slippage=0.01%",
    "okx-security: native_asset=true, risk_score=1",
    "okx-wallet-portfolio: position=5%"
  ]
}
```

### Step 5: Execution
The agent receives the SAFE verdict and proceeds to execute the trade using the `okx-dex-swap` skill.

```
Agent: "Risk check passed. Proceeding with trade..."
Agent: "Executing swap: 1000 USDC → ~5.56 SOL"
Agent: "Trade executed successfully. New balance: 7.56 SOL"
```

## Key Takeaways
- **Deterministic:** The verdict is based on objective data, not probabilistic LLM reasoning.
- **Transparent:** Every decision is cited with sources.
- **Safe:** The trade passes all risk checks and is executed confidently.
