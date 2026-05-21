---
name: geckovision-risk-oracle
description: A grounded risk oracle that prevents AI trading agents from hallucinating or executing unsafe trades. Analyzes token risk, market structure, and portfolio impact before execution.
version: 1.0.0
author: GeckoVision
tags: [risk-management, security, trading-bot, onchainos, solana, ethereum, guardrails, defi]
triggers:
  - "Is this safe to trade?"
  - "Check risk for [token]"
  - "Should I buy [token]?"
  - "Analyze risk before swapping"
  - "GeckoVision risk check"
  - "Risk assessment for [token]"
  - "Is [token] safe?"
dependencies:
  - okx-dex-token
  - okx-dex-market
  - okx-wallet-portfolio
  - okx-security
---

# GeckoVision Risk Oracle

## Goal
Prevent AI trading agents from hallucinating or executing unsafe trades by providing a deterministic risk assessment before any trade execution. This skill acts as a safety guardrail, analyzing token risk, market structure, and portfolio impact to help traders make informed decisions.

## Why This Matters
Financial transactions require deterministic guarantees, but LLMs are probabilistic. When an agent hallucinates a trade (e.g., recommending a fraudulent token or ignoring portfolio concentration), real capital is lost. The GeckoVision Risk Oracle fills this gap by refusing to execute trades when evidence is insufficient.

## How It Works

### Step 1: Trigger Detection
The agent detects when the user or another agent is about to execute a swap or trade. Common triggers include:
- "Should I buy [token]?"
- "Is this safe to trade?"
- "Check risk for [token]"
- "Analyze risk before swapping"

### Step 2: Data Gathering
The agent uses OnchainOS skills to gather critical data:
- **okx-dex-token:** Token metadata, market cap, liquidity pools, holder distribution
- **okx-dex-market:** Real-time price, trading volume, K-line charts, volatility
- **okx-wallet-portfolio:** User's current holdings, portfolio composition, balance
- **okx-security:** Smart contract risk score, phishing detection, approval safety

### Step 3: Risk Analysis
The agent evaluates the gathered data against the GeckoVision Risk Matrix:

| Risk Factor | Threshold | Verdict Impact |
|---|---|---|
| **Liquidity Depth** | < $50k | REJECT |
| **Market Cap** | < $100k | REJECT |
| **Age** | < 24 hours | REJECT |
| **Contract Verified** | No | DEFER |
| **Holder Concentration** | > 50% top 10 | DEFER |
| **Portfolio Concentration** | > 30% in sector | DEFER |
| **Swap Slippage** | > 5% | DEFER |
| **Known Phishing** | Yes | REJECT |

### Step 4: Verdict Generation
The agent outputs a JSON response with a clear verdict and reasoning:

```json
{
  "verdict": "SAFE | DEFER | REJECT",
  "confidence_score": 0-100,
  "risk_factors": ["factor1", "factor2"],
  "reasoning": "Clear explanation of the verdict",
  "recommendation": "Actionable next steps",
  "citations": ["source1", "source2"]
}
```

### Step 5: Execution Gate
- **SAFE:** Agent proceeds with the trade.
- **DEFER:** Agent asks the user for explicit confirmation before proceeding.
- **REJECT:** Agent refuses to execute and explains why.

## Output Format (JSON)
Always return a structured JSON response. The agent must parse this response to make execution decisions.

```json
{
  "verdict": "SAFE",
  "confidence_score": 85,
  "risk_factors": [],
  "reasoning": "The token has $2.5M liquidity, verified contract, and no known vulnerabilities. Portfolio concentration is within safe limits.",
  "recommendation": "Proceed with trade. Consider using a limit order to avoid slippage.",
  "citations": ["okx-dex-token: liquidity=$2.5M", "okx-security: contract_verified=true"]
}
```

## Examples

### Example 1: SAFE Trade
**User Request:** "Should I buy 1000 USDC worth of SOL on Solana?"

**GeckoVision Analysis:**
- Liquidity: $500M+ ✓
- Market Cap: $150B+ ✓
- Contract: Verified ✓
- Portfolio Impact: 5% (low) ✓

**Output:**
```json
{
  "verdict": "SAFE",
  "confidence_score": 95,
  "risk_factors": [],
  "reasoning": "SOL is a major blockchain asset with deep liquidity, verified contract, and minimal portfolio concentration risk.",
  "recommendation": "Proceed with trade.",
  "citations": ["okx-dex-market: liquidity=$500M+", "okx-security: contract_verified=true"]
}
```

### Example 2: DEFER Trade
**User Request:** "Should I buy 1000 USDC worth of NEW_TOKEN on Solana?"

**GeckoVision Analysis:**
- Liquidity: $500k ✓
- Market Cap: $5M ✓
- Contract: Unverified ⚠️
- Holder Concentration: 45% in top 10 ⚠️

**Output:**
```json
{
  "verdict": "DEFER",
  "confidence_score": 60,
  "risk_factors": ["Unverified smart contract", "High holder concentration (45% in top 10)"],
  "reasoning": "The token has reasonable liquidity but the contract is unverified and holder distribution is concentrated. This is a moderate-risk trade.",
  "recommendation": "Verify the contract audit before proceeding. Consider reducing trade size by 50%.",
  "citations": ["okx-security: contract_verified=false", "okx-dex-token: holder_concentration=45%"]
}
```

### Example 3: REJECT Trade
**User Request:** "Should I buy 1000 USDC worth of SCAM_TOKEN on Solana?"

**GeckoVision Analysis:**
- Liquidity: $10k ✗
- Market Cap: $50k ✗
- Age: 2 hours ✗
- Phishing Detection: Known scam ✗

**Output:**
```json
{
  "verdict": "REJECT",
  "confidence_score": 99,
  "risk_factors": ["Critically low liquidity ($10k)", "Very new token (2 hours old)", "Known phishing/scam pattern", "Insufficient market data"],
  "reasoning": "This token exhibits multiple hallmarks of a rug pull or scam: extremely low liquidity, very recent creation, and known phishing patterns. Executing this trade would likely result in capital loss.",
  "recommendation": "Do not proceed. This token is flagged as high-risk.",
  "citations": ["okx-dex-token: liquidity=$10k", "okx-security: phishing_detected=true", "okx-dex-market: age=2h"]
}
```

## Error Handling

### Insufficient Data
If OnchainOS skills fail to return necessary data:
```json
{
  "verdict": "DEFER",
  "confidence_score": 0,
  "risk_factors": ["Insufficient data"],
  "reasoning": "Unable to retrieve token data from OnchainOS. Cannot assess risk.",
  "recommendation": "Try again in a few moments or manually verify the token on a blockchain explorer.",
  "citations": []
}
```

### Token Not Found
If the token is not found on any supported DEX:
```json
{
  "verdict": "REJECT",
  "confidence_score": 100,
  "risk_factors": ["Token not found on supported DEX"],
  "reasoning": "The token does not exist on any supported DEX (Solana, Ethereum, etc.). This may indicate a typo or a scam.",
  "recommendation": "Verify the token address and try again.",
  "citations": []
}
```

## Token Efficiency
- **Average Tokens per Query:** 500-800 tokens
- **Optimization:** Only request necessary data from OnchainOS skills. Cache results when possible.
- **Fallbacks:** Default to DEFER if data is incomplete, not REJECT (unless there's clear evidence of fraud).

## Security Considerations
- **No Custody:** This skill does not hold or manage user funds. All transactions are signed by the user's TEE-protected wallet.
- **Audit Trail:** Every verdict is logged with citations for compliance and debugging.
- **Transparency:** All reasoning is explicit and explainable, not a black box.

## Integration with OnchainOS
This skill works seamlessly with the following OnchainOS skills:
- **okx-dex-token:** Provides token metadata and holder analysis
- **okx-dex-market:** Provides real-time price and volume data
- **okx-wallet-portfolio:** Provides user's current holdings and portfolio composition
- **okx-security:** Provides contract risk scores and phishing detection
- **okx-dex-swap:** Executes the trade after GeckoVision approval

### Typical Workflow
```
User: "Should I buy 1000 USDC of [TOKEN]?"
  ↓
GeckoVision Risk Oracle: Gathers data from okx-dex-token, okx-dex-market, okx-wallet-portfolio, okx-security
  ↓
GeckoVision Risk Oracle: Analyzes risk and outputs verdict (SAFE/DEFER/REJECT)
  ↓
If SAFE: Agent proceeds to okx-dex-swap
If DEFER: Agent asks for user confirmation
If REJECT: Agent refuses and explains why
```

## Monetization
This skill is monetized via the OKX x402 payment protocol. Each risk assessment query costs a small amount of USDC (e.g., $0.01-0.05), paid automatically by the agent or user.

## Support
For questions or issues, contact GeckoVision support or open an issue on the GitHub repository.
