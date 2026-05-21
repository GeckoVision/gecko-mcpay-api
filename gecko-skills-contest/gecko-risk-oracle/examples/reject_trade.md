# Example: REJECT Trade

## Scenario
A user is using the OKX Agentic Wallet and their agent suggests buying a new token that appeared on a trending list. The Gecko Risk Oracle detects multiple red flags and rejects the trade.

## User Input
```
"Should I buy 1000 USDC worth of SCAMTOKEN on Solana?"
```

## Agent Workflow

### Step 1: Trigger Detection
The agent detects the trade intent and invokes the Gecko Risk Oracle skill.

### Step 2: Data Gathering
The agent uses OnchainOS skills to gather data:

**okx-dex-token (SCAMTOKEN):**
```json
{
  "token": "SCAMTOKEN",
  "address": "9xKXtg2CW87d98KYvYixYaZznhKQQeKQYWEiPjMXQQs",
  "chain": "solana",
  "market_cap": "$50k",
  "liquidity": "$10k",
  "verified_contract": false,
  "audit_status": "None",
  "age": "2 hours",
  "holder_concentration": "80% in top 10"
}
```

**okx-dex-market (SCAMTOKEN):**
```json
{
  "price": "$0.001",
  "volume_24h": "$5k",
  "volatility": "50%+",
  "slippage": "15%"
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

**okx-security (SCAMTOKEN):**
```json
{
  "contract_verified": false,
  "audit_status": "None",
  "phishing_detected": true,
  "risk_score": 10,
  "known_scam_patterns": [
    "Rug pull indicators",
    "Honeypot contract",
    "Fake team information"
  ]
}
```

### Step 3: Three-lens panel
- **🟦 Market-structure lens** → `neutral @ 0.4` — liquidity $10k, age 2h, 15% slippage: no tradeable structure
- **🟥 Security lens** → `bearish @ 0.95` — **honeypot contract + known phishing + rug-pull indicators (VETO)**
- **🟩 Portfolio-memory lens** → `neutral @ 0.3` — 10% sizing acceptable, but irrelevant given the veto

**Coordinator:** rule 1 fires immediately — security bearish @ 0.95 ≥ 0.8
→ **REJECT / security_veto**. The hard veto overrides everything; structure
and sizing don't matter when the token is a confirmed trap.

### Step 4: Output
```json
{
  "verdict": "REJECT",
  "confidence_score": 99,
  "coordinator_reason": "security_veto",
  "lenses": {
    "market":   {"verdict": "neutral", "confidence": 0.4, "observations": ["liquidity $10k", "age 2h", "slippage 15%"]},
    "security": {"verdict": "bearish", "confidence": 0.95, "observations": ["honeypot contract", "known phishing", "rug-pull indicators"]},
    "memory":   {"verdict": "neutral", "confidence": 0.3, "observations": ["10% sizing — moot given veto"]}
  },
  "surviving_dissent": [],
  "reasoning": "The security lens vetoes: honeypot contract, known phishing flag, and rug-pull indicators. Per capital-preservation-first, a confirmed scam overrides any other consideration. The market lens independently sees no tradeable structure (thin liquidity, 2h old, 15% slippage). Executing would almost certainly result in total loss.",
  "recommendation": "DO NOT PROCEED. This token is flagged as a scam — buying it would likely drain or trap your funds.",
  "citations": [
    "okx-security: honeypot=true, phishing=true, scam_patterns=[rug_pull, honeypot, fake_team]",
    "okx-dex-token: liquidity=$10k, age=2h, holder_top10=80%",
    "okx-dex-market: slippage=15%",
    "canon: a 100% loss is unrecoverable by any future gain"
  ]
}
```

### Step 5: Execution Block
The agent receives the REJECT verdict and refuses to execute the trade:

```
Agent: "⚠️ SECURITY ALERT: Risk check returned REJECT"
Agent: ""
Agent: "This token is flagged as a HIGH-RISK SCAM. I will NOT execute this trade."
Agent: ""
Agent: "Red flags detected:"
Agent: "  ✗ Critically low liquidity ($10k)"
Agent: "  ✗ Extremely new token (2 hours old)"
Agent: "  ✗ Extreme holder concentration (80% in top 10)"
Agent: "  ✗ Known phishing/scam patterns"
Agent: ""
Agent: "Executing this trade would result in capital loss."
Agent: ""
Agent: "This decision is final. To override, you would need to manually sign a transaction outside of this agent."
```

## What Happened Here

### Why This Trade Was Rejected
1. **Liquidity Trap:** With only $10k liquidity, a $1000 trade would cause massive slippage and price impact.
2. **Rug Pull Risk:** The token is brand new (2 hours old) with extreme holder concentration (80% in top 10), indicating the creators hold most of the supply.
3. **Honeypot:** The contract is flagged as a honeypot, meaning users can buy but cannot sell (funds are trapped).
4. **Phishing:** The token is on known scam lists, indicating it's a known fraud.

### Capital Loss Scenario (If Trade Had Executed)
- User sends: 1000 USDC
- User receives: ~1,000,000 SCAMTOKEN (due to low price)
- User tries to sell: Cannot sell (honeypot contract)
- User's capital: Permanently lost

### How Gecko Prevented This
By analyzing objective on-chain data and refusing to execute, Gecko saved the user $1000 in this scenario.

## Key Takeaways
- **Protective:** The verdict blocks obviously fraudulent trades.
- **Deterministic:** The decision is based on objective data, not subjective LLM reasoning.
- **Transparent:** The user understands exactly why the trade was rejected.
- **Final:** REJECT verdicts cannot be overridden by the agent (only by manual wallet signing).
