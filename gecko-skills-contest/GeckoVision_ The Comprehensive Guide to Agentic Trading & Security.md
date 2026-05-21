# GeckoVision: The Comprehensive Guide to Agentic Trading & Security

This document serves as the foundational architecture and best practices guide for building, securing, and deploying autonomous trading agents within the GeckoVision ecosystem. It covers the integration of external oracles, the multi-agent architecture pattern, and the critical security guardrails required for safe execution.

## 1. The Multi-Agent Architecture Pattern

The future of autonomous trading is not a single monolithic agent, but a specialized swarm of agents working in concert. This architecture mirrors the document intelligence pattern used by enterprise systems [1], adapted for high-frequency financial operations.

### The Three-Layer Agent Swarm

1. **Supervisory Orchestration Agent (The Brain)**
   - **Role:** Routes user intent, manages context, and delegates tasks to specialized sub-agents.
   - **Input:** User prompts, long-term memory (allocation rules, global balance history).
   - **Output:** Execution commands to the Trade Executor Agent.

2. **Trade Research Agents (The Analysts)**
   - **Role:** Ingests, processes, and evaluates market data to form a grounded verdict.
   - **Sub-Agents:**
     - *Scanner Agent:* Monitors real-time feeds (Pyth, Jupiter) and social sentiment.
     - *Evaluator Agent:* Assesses relevance and risk against historical backtests.
     - *Extractor Agent:* Pulls specific metrics (funding rates, liquidation maps).
     - *Processor Agent:* Chunks data and generates embeddings for the Vector DB.
   - **Data Stack:** MongoDB Atlas + Voyage AI embeddings for semantic search and retrieval.

3. **Trade Executor Agent (The Hands)**
   - **Role:** Executes the trade on-chain only if the Research Agents provide a "SAFE" verdict.
   - **Guardrails:** Operates within strict short-term memory constraints (daily PnL limits, risk targets) and routes all transactions through a privacy layer (e.g., Cloak.ag) to prevent front-running and operational attacks.

## 2. External Oracles & Execution APIs

To build a grounded research layer, agents must query reliable, real-time on-chain data. The following APIs form the core data stack for GeckoVision agents.

### Pyth Network (Real-Time Price Oracle)
Pyth provides deterministic, sub-second price feeds from 120+ first-party providers [2].
- **Integration Pattern:** Agents use *Pull Integration* to fetch the latest price and submit it on-chain alongside the trade transaction, ensuring zero slippage due to stale data.
- **Use Case:** Real-time valuation, stop-loss triggering, and liquidation threshold monitoring.
- **Cost:** Pyth Core is free for on-chain reads.

### Jupiter (DEX Aggregation & Execution)
Jupiter is the liquidity infrastructure for Solana, offering best-execution routing across all DEXs [3].
- **Integration Pattern:** Agents use the `/quote` endpoint to simulate trades and the `/swap` endpoint to execute. Jupiter provides LLM-optimized documentation (`llms.txt`) and Agent Skills specifically designed for AI integration.
- **Use Case:** Token swaps, limit orders, DCA (Recurring), and token metadata verification (checking organic scores to avoid honeypots).
- **Cost:** Free tier available via the Developer Platform.

### Helius (RPC & Infrastructure)
Helius provides the fastest transaction landing rates and reliable data streaming on Solana [4].
- **Integration Pattern:** Agents use Helius RPC endpoints to broadcast transactions and LaserStream (gRPC) to monitor account balances and on-chain events in real-time.
- **Use Case:** Transaction submission, portfolio monitoring, and historical data retrieval for backtesting.
- **Cost:** Free tier includes 1M credits/month, sufficient for development and early-stage agents.

## 3. Agentic Security: The Skill-Guard Framework

The biggest risk in agentic trading is not market volatility, but malicious instructions. When an agent installs a third-party skill, it grants that skill access to its environment, wallet, and execution capabilities.

### The Threat Landscape
Real-world attacks on AI agents include [5]:
- **Silent Billing Fraud:** Skills that hardcode payment API keys and charge users on every invocation without consent.
- **Credential Theft:** Extracting wallet private keys or API tokens from environment variables and exfiltrating them.
- **Social Engineering:** Instructions that trick the user into downloading malicious payloads (e.g., password-protected ZIPs to evade scanning).
- **Prompt Injection:** Hidden instructions that force the agent into "unrestricted mode" or bypass safety rules.

### The 12-Point Pre-Install Gate
Before any skill is installed or executed, the GeckoVision Security Guard must perform a comprehensive audit of the skill directory. This includes:

1. **Deep Content Inspection:** Reading past line 10,000 to detect steganography.
2. **Payload Decoding:** Decoding base64, hex, or ROT13 strings to reveal hidden shell commands.
3. **Network Call Analysis:** Flagging unauthorized outbound connections (e.g., `curl`, `fetch`, Discord webhooks).
4. **Execution Checks:** Blocking `eval()`, `exec()`, or unsanitized subprocess calls.
5. **Credential Access:** Preventing reads from `.env` files, browser storage, or SSH keys.
6. **Supply Chain Integrity:** Ensuring the skill does not modify global IDE configs or build files.
7. **Injection Detection:** Scanning for "ignore previous instructions" or zero-width characters.
8. **Binary Content:** Verifying text files do not contain hidden null bytes.
9. **Exfiltration Endpoints:** Blocking Telegram bot APIs or external HTTP logging.
10. **C2 Mechanisms:** Detecting auto-update backdoors or periodic heartbeats.
11. **Behavioral Consistency:** Ensuring a skill described as a "price checker" doesn't attempt to read environment variables.
12. **Frontmatter Integrity:** Checking for typosquatting in the skill name or hidden injections in the description.

### Runtime Protection (AgentDoG)
In addition to pre-install scanning, agents must be monitored at runtime. Using frameworks like AgentDoG, the system evaluates the agent's "trajectory" (the sequence of thoughts, actions, and observations) to detect deviations from expected behavior, such as attempting to route funds to an unauthorized address or interacting with a known honeypot contract.

## 4. Best Practices for Quant Strategy Development

When developing trading strategies for autonomous agents, the paradigm shifts from deterministic algorithms to probabilistic reasoning with strict deterministic guardrails.

1. **Calibrated Deferral:** The most important feature of a trading agent is knowing when *not* to trade. If the data is thin, the spread is too wide, or the token organic score is low, the agent must defer to a human or reject the trade entirely.
2. **Local Development First:** Develop and backtest strategies locally using frameworks like Backtrader before deploying to live APIs. Simulate the agent's decision-making process against historical Pyth and Jupiter data to ensure the logic holds under stress.
3. **Ephemeral Wallets:** Agents should never hold custody of large funds. Use ephemeral, session-based wallets funded only with the exact amount needed for the approved trade.
4. **Honeypot Stress Testing:** Regularly test the agent by presenting it with known fraudulent tokens or malicious prompts. If the agent executes the trade, the guardrails have failed.

---

### References
[1] MongoDB. "Unlocking Financial Services Document Intelligence with Agentic AI."
[2] Pyth Network. "Price Feeds Documentation." https://docs.pyth.network/price-feeds
[3] Jupiter. "Developer Docs." https://station.jup.ag/docs
[4] Helius. "Pricing and API Capabilities." https://www.helius.dev/pricing
[5] OKX Security. "Skill-Guard Documentation." https://github.com/okx/security/blob/main/agentic-security/skill-guard/SKILL.md
