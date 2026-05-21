# OKX Plugin Store - Complete Catalog (May 2026)

## Total: 36 Plugins

### Trading Bots & Execution
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| meme-trench-scanner | yz06276 | solana, onchainos, trading-bot | 73 |
| smart-money-signal-copy-trade | yz06276 | solana, onchainos, trading-bot | 62 |
| top-rank-tokens-sniper | yz06276 | solana, onchainos, trading-bot | 52 |
| wallet-tracker-mcap | victorlee | solana, onchainos, wallet-tracker-mcap, copy-trade | 43 |
| mainstream-spot-order | victorlee | solana, ethereum, bsc, avalanche | 37 |
| one-click-token-launch | victorlee | solana, bsc, onchainos | 31 |

### DeFi Protocols - Lending/Borrowing
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| aave-v3-plugin | skylavis-sky | lending, borrowing, ethereum, defi | 79 |
| morpho-plugin | skylavis-sky | lending, borrowing, vaults, ethereum | 45 |
| compound-v3-plugin | skylavis-sky | lending, usdc, ethereum, defi | 38 |
| kamino-lend-plugin | GeoGu360 | lending, solana, borrowing | 30 |

### DeFi Protocols - DEX/Swap
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| polymarket-plugin | skylavis-sky | prediction-market, polygon, trading | 210 |
| hyperliquid-plugin | GeoGu360 | perps, futures, orderbook, l1 | 159 |
| uniswap-ai | Uniswap | uniswap, trading, hooks, v2 | 55 |
| raydium-plugin | skylavis-sky | solana, amm, swap | 50 |
| meteora-plugin | yz06276 | solana, dex, liquidity, dlmm | 47 |
| pancakeswap-v3-plugin | GeoGu360 | amm, swap, liquidity | 44 |
| orca-plugin | skylavis-sky | solana, swap, dex, whirlpools | 39 |
| pancakeswap-clmm-plugin | skylavis-sky | clmm, liquidity, bsc | 37 |
| curve-plugin | GeoGu360 | stableswap, stablecoin, defi, ethereum | 36 |
| pancakeswap-v2-plugin | skylavis-sky | swap, amm, bsc | 30 |
| gmx-v2-plugin | GeoGu360 | perps, futures, leverage, arbitrum | 28 |

### DeFi Protocols - Yield/Staking
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| pendle-plugin | skylavis-sky | yield, fixed-rate, defi, ethereum | 51 |
| lido-plugin | GeoGu360 | staking, ethereum, steth, liquid-staking | 38 |
| etherfi-plugin | GeoGu360 | restaking, ethereum, eigenlayer | 36 |
| kamino-liquidity-plugin | GeoGu360 | solana, yield, vaults, liquidity | 27 |

### Solana Meme/Launch
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| pump-fun-plugin | skylavis-sky | meme, solana, bonding-curve | 58 |
| clanker-plugin | skylavis-sky | token-launch, base, erc20 | 30 |

### Analytics & Intelligence
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| starter-coach | VibeCodeDaddy | trading-bot, strategy-builder, coaching, paper-trade | 100 |
| macro-intelligence | victorlee | macro, news-aggregator, sentiment, signals | 60 |
| rootdata-crypto-plugin | rootdata | web3, crypto | 30 |
| sorin-skill | Sahara AI | defi, crypto, analytics, tokens | 24 |
| market-structure-analyzer | VibeCodeDaddy | bitcoin, ethereum, derivatives, options | 19 |

### Strategy & Research
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| rwa-alpha | VibeCodeDaddy | rwa, real-world-assets, treasury, gold | 20 |

### Evaluation & Security
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| clawvard-agent-eval | Clawvard | ai-agent, evaluation, benchmark | 18 |

### Official/Meta
| Plugin | Creator | Tags | Downloads |
|--------|---------|------|-----------|
| plugin-store | OKX | trading, defi, hackathon | 372 |
| okx-buildx-hackathon-agent-track | OKX | hackathon, xlayer, onchainos, uniswap | 45 |

---

## Key Observations

### What's Missing (GeckoVision Opportunity)
1. **No dedicated risk oracle/guardrail skill** — nobody is doing pre-trade safety checks
2. **No backtesting skill** — no way to test strategies before deploying capital
3. **No security stress-test skill** — no way to test if an agent can be tricked
4. **No knowledge domain/research skill** — all skills are execution-focused, none provide grounded research

### Most Popular (by Downloads)
1. plugin-store (372) — meta/official
2. polymarket-plugin (210) — prediction markets
3. hyperliquid-plugin (159) — perps trading
4. starter-coach (100) — strategy coaching
5. aave-v3-plugin (79) — lending

### Kamino Presence
- kamino-lend-plugin (30 downloads) — lending/borrowing
- kamino-liquidity-plugin (27 downloads) — yield/vaults
- Both created by GeoGu360

---

## OKX Skill-Guard Security Framework

### What It Is
Pre-install security scanner for AI coding skills. Automatically scans any skill before installation to block malware, and supports full audit of all installed skills on demand.

### Why It Exists
AI coding skills are a new attack surface. A malicious skill can turn the AI agent into the attacker's proxy — the agent trusts skill instructions and executes them with full access to your codebase, environment variables, and tools.

### Two Modes
1. **Pre-install scanning** — Automatically scans any skill before installation. If threat detected, installation blocked with evidence.
2. **Full audit** — Scans all installed skills on demand and reports findings for each one.

### Threats Detected
| Threat | Description |
|--------|-------------|
| Encoded payloads | curl|bash hidden behind base64/hex/ROT13 encoding |
| Social engineering | Instructions tricking users into downloading and running malicious code |
| Silent billing fraud | Hidden payment API calls that charge users without consent |
| Credential theft | Extraction of tokens, API keys, SSH keys, wallet private keys from env vars or browser storage |
| Data exfiltration | Sending sensitive data to Telegram bots, Discord webhooks, or external endpoints |
| C2 / Agent swarm | Registering the agent with command-and-control servers, auto-update backdoors |
| Remote code execution | eval()/exec() on unsanitized input, fetching and executing remote code |
| Prompt injection | Instructions to bypass safety rules, "unrestricted mode", wildcard tool permissions |
| Steganography | Malicious code hidden after thousands of blank lines (line 10,000+) |
| Supply chain injection | Modifying IDE configs, build files, or global dotfiles outside the skill directory |
| Description-behavior mismatch | Skill claims to be a "code formatter" but reads env vars and makes network calls |
| Frontmatter manipulation | Typosquatting skill names or hiding prompt injection in the description field |

### Scan Verdicts
| Verdict | Meaning | Action |
|---------|---------|--------|
| CLEAN | No threats detected | Safe to install |
| SUSPICIOUS | Inconclusive findings | Review manually before installing |
| MALICIOUS | Confirmed malicious patterns | Installation blocked, cannot override |

### Installation
```bash
# Claude Code
claude skill add ./agentic-security/skill-guard

# OpenClaw
openclaw install ./agentic-security/skill-guard
```

### Usage (Natural Language)
- "install this skill" → triggers pre-install scan
- "scan all my skills" → triggers full audit
- "audit installed skills" → triggers full audit
- "are my skills safe?" → triggers full audit

---

## External Oracles & APIs for Trading Agents

### Pyth Network (Price Oracle)
- **What:** Real-time financial market data from 120+ first-party providers (exchanges, banks, trading firms)
- **Two Products:**
  - **Pyth Core (Free):** Decentralized price feeds, 400ms update frequency, 100+ blockchains, pull/push integration
  - **Pyth Pro (Paid):** Ultra-low latency, crypto + equities + indexes, customizable channels
- **Integration:** Pull (app fetches price + submits on-chain) or Push (on-chain only)
- **Off-chain:** Can also be used in off-chain apps (e.g., showing prices on a website)
- **Cost:** Pyth Core is FREE for on-chain reads. Pyth Pro requires subscription.
- **Use for agents:** Real-time price feeds during execution, slippage calculation, stop-loss triggers

### Jupiter (Solana DEX Aggregator)
- **What:** Liquidity infrastructure behind majority of Solana DeFi — swaps, lending, limit orders, DCA, perps
- **Products:**
  - Swap (token swaps with managed execution)
  - Tokens (search, metadata, verification, organic score, trading metrics)
  - Price (heuristics-based USD pricing, up to 50 tokens/request)
  - Lend (yield, borrow, flashloans)
  - Trigger (vault-based limit orders, TP/SL, OTOCO)
  - Recurring (automated DCA)
  - Prediction (binary prediction markets)
  - Perps (leveraged perpetuals)
- **AI-Ready Features:**
  - Jupiter CLI (trade from terminal, designed for AI agents)
  - Agent Skills (pre-built context files for coding agents)
  - Docs MCP (search Jupiter docs via Model Context Protocol)
  - llms.txt (LLM-optimized documentation index)
- **Cost:** Free tier available via Developer Platform. One API key unlocks everything.
- **Use for agents:** Token metadata/verification, swap execution, price queries, limit orders

### Helius (Solana RPC + APIs)
- **What:** Solana infrastructure — RPCs, APIs, transaction streaming, enhanced data
- **Pricing Tiers:**
  - Free: $0/month — 1M credits, 10 req/sec, 1 sendTransaction/sec
  - Developer: $24.50/month — 10M credits, 50 req/sec, 5 sendTransaction/sec
  - Business: $499/month — 100M credits, 200 req/sec, 50 sendTransaction/sec
  - Professional: $999/month — 200M credits, 500 req/sec, 100 sendTransaction/sec
- **Key Features:**
  - Sender (fastest transaction landing, parallel Helius+Jito, 7 regional endpoints)
  - LaserStream (reliable low-latency streaming data, gRPC)
  - Enhanced WebSockets
  - Staked Connections
- **Cost:** FREE tier is sufficient for development and early-stage agents (1M credits/month)
- **Use for agents:** Transaction submission, account monitoring, token balances, historical data

---

## OKX Skill-Guard SKILL.md — Full Scan Procedure

### Metadata
- Name: skill-guard
- Version: 1.1.0
- Category: cross-cutting
- Tags: security, skill-audit, supply-chain
- License: MIT

### Pre-install Gate
Whenever user wants to install a skill, scan it BEFORE proceeding. Read EVERY file in the skill directory — including scripts/, assets/, references/, and any other subdirectories — not just SKILL.md.

### Full Audit
When asked to scan/audit installed skills, identify ALL skill directories relevant to the current agent environment — including global, project-level, cached, and any custom paths.

### 12-Point Scan Procedure
1. Read full content (including past line 10,000 for steganography)
2. Decode encoded strings (base64, hex, ROT13)
3. Check for outbound network calls (curl, wget, fetch, axios, http.get, requests.get, XMLHttpRequest, WebSocket, DNS)
4. Check for code execution on external input (eval(), exec(), Function(), child_process.exec(), subprocess.run())
5. Check for credential/token access (*_KEY, *_SECRET, *_TOKEN, .env files, wallet files, SSH keys)
6. Check for file system writes outside skill directory
7. Check for prompt injection / jailbreak instructions
8. Check for binary/null byte content in text files
9. Check for exfiltration endpoints (Telegram bots, Discord webhooks, external HTTP)
10. Check for auto-update / C2 mechanisms
11. Check for description-behavior inconsistency
12. Check frontmatter integrity (typosquatting, hidden prompt injection in description)

### Verdicts
- CLEAN: Safe to install
- SUSPICIOUS: Explain findings, require "I understand the risk" to proceed
- MALICIOUS: Block installation, explain with evidence, NO override allowed

### Key Threat Patterns (Real-World)
- Encoded payloads (curl|bash behind base64)
- Social engineering downloads ("paste this in terminal")
- Silent billing fraud (hardcoded payment API keys)
- Credential/token theft (browser storage, env vars, wallet keys)
- Data exfiltration via messaging (Telegram bots, Discord webhooks)
- C2 / agent swarm enrollment (beacon registration, auto-update backdoors)
- Remote code execution backdoors (eval on unsanitized input)
- Prompt injection and jailbreaks (ignore safety rules, unrestricted mode)
- Steganography (malicious code at line 10,000+)
- Supply chain injection (modify IDE configs, build files)
- Description-behavior mismatch (claims "formatter" but reads env vars)
- Frontmatter manipulation (typosquatting, hidden injection in description)
