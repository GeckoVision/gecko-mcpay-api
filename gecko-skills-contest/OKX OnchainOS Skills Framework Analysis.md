# OKX OnchainOS Skills Framework Analysis

## Key Findings

### Existing Skills Pattern (Starter Coach Example)
- **Conversational 6-step flow:** Onboard → Profile → Build Strategy → Backtest → Paper Trade → Go Live
- **JSON strategy spec generation** from user inputs
- **Historical backtesting** with performance metrics
- **Paper trading requirement** before live mode
- **Explicit CONFIRM acknowledgment** for risk gating
- **DEX execution** via OnchainOS Agentic Wallet (TEE signing)
- **Tags:** trading-bot, strategy-builder, dex, onchainos, solana, ethereum, paper-trade

### OnchainOS Skills Ecosystem
The framework provides 15+ pre-built skills that work together:
- **okx-agentic-wallet:** Wallet lifecycle (auth, balance, portfolio PnL, send, tx history)
- **okx-security:** Security scanning (token risk, DApp phishing, tx pre-execution, signature safety)
- **okx-dex-market:** Real-time prices, K-line charts, index prices, wallet PnL analysis
- **okx-dex-swap:** Token swap via DEX aggregation (500+ liquidity sources)
- **okx-dex-token:** Token search, metadata, market cap, rankings, liquidity pools
- **okx-dex-signal:** Smart money/whale/KOL signal tracking, leaderboard rankings
- **okx-onchain-gateway:** Gas estimation, transaction simulation, broadcasting, order tracking
- **okx-defi-invest:** DeFi product discovery, deposit, withdraw, claim rewards (Aave, Lido, PancakeSwap, Kamino, NAVI)
- **okx-agent-payments-protocol:** Unified payment dispatcher (x402, MPP, a2a-pay)

### Skill Workflow Patterns
1. **Search and Buy:** okx-dex-token → okx-wallet-portfolio → okx-dex-swap
2. **Portfolio Overview:** okx-wallet-portfolio → okx-dex-token → okx-dex-market
3. **Market Research:** okx-dex-token → okx-dex-market → okx-dex-swap
4. **Full Trading Flow:** okx-dex-token → okx-dex-market → okx-wallet-portfolio → okx-dex-swap → okx-onchain-gateway
5. **Leaderboard → Research → Trade:** okx-dex-signal → okx-dex-token → okx-dex-swap

### Supported Chains
XLayer, Solana, Ethereum, Base, BSC, Arbitrum, Polygon, and 20+ others

### Installation
- **Recommended:** `npx skills add okx/onchainos-skills`
- Works with: Claude Code, Cursor, Codex CLI, OpenCode, OpenClaw

## GeckoVision Risk Oracle Skill Opportunity

### Where It Fits in the Workflow
**Before execution in any trading flow:**
- okx-dex-token (search) → okx-dex-market (price/chart) → **[GECKO_RISK_CHECK]** → okx-dex-swap (execute trade)
- okx-dex-signal (top traders) → okx-dex-token (token analytics) → **[GECKO_RISK_CHECK]** → okx-dex-swap (execute trade)

### Key Integration Points
1. **Trigger:** User asks "Is this safe to trade?", "Check risk", "Should I buy?", etc.
2. **Input:** Token address, amount, chain, user's wallet balance/portfolio
3. **Output:** SAFE / DEFER / REJECT with reasoning and citations
4. **Integration:** Works with okx-dex-token, okx-wallet-portfolio, okx-security
5. **Monetization:** x402 payment protocol (already in OnchainOS)

### What Makes a Winning Skill
Based on Starter Coach and scoring criteria:
1. **Clear trigger keywords** for varied user phrasings
2. **Structured YAML metadata** with proper frontmatter
3. **JSON output format** for agent parsing
4. **Error handling and fallbacks** for edge cases
5. **Reasonable token usage** (efficient prompts)
6. **Real executability** when run with an agent
7. **Originality** (no existing risk oracle in the Plugin Store)
