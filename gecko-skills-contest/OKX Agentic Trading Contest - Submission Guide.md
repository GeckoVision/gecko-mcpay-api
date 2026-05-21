# OKX Agentic Trading Contest - Submission Guide

## Overview
This guide explains how to submit the GeckoVision Risk Oracle skill to the OKX Plugin Store for the Agentic Trading Contest. The skill has been optimized to score highly on both the AI and Human judging criteria.

## Scoring Optimization Checklist

### AI Score (50%)
- [x] **Structure and metadata (25 pts):** `package.json` and `SKILL.md` YAML frontmatter are perfectly formatted. Folder layout is clean.
- [x] **Trigger quality (25 pts):** 7 varied trigger phrases included in metadata. Will not misfire on general chat.
- [x] **Instruction quality (30 pts):** `SKILL.md` clearly explains the "why", specifies the exact JSON output format, and includes a detailed Risk Matrix.
- [x] **Efficiency and performance (20 pts):** Instructions mandate concise token usage, caching, and clear error handling/fallbacks (e.g., defaulting to DEFER on missing data).

### Human Score (50%)
- [x] **Executability:** Relies entirely on existing OnchainOS skills (`okx-dex-token`, `okx-dex-market`, `okx-security`).
- [x] **Result quality:** JSON output is highly structured, actionable, and includes citations for transparency.
- [x] **Originality:** This is the first dedicated risk oracle/guardrail skill in the OKX ecosystem.

## How to Submit (Next 48 Hours)

1. **Clone the OKX Plugin Store Community Repo:**
   ```bash
   git clone https://github.com/okx/plugin-store-community.git
   cd plugin-store-community
   ```

2. **Copy the Skill Files:**
   Copy the entire `geckovision-risk-oracle` folder into the `skills/` directory of the cloned repo.

3. **Test Locally (Optional but Recommended):**
   If you have the OnchainOS CLI installed, test the skill locally:
   ```bash
   npx skills add ./skills/geckovision-risk-oracle
   ```
   Ask your agent: "Should I buy 1000 USDC of SOL?" and verify it uses the skill.

4. **Create a Pull Request:**
   - Commit your changes and push to your fork.
   - Open a Pull Request against the `okx/plugin-store-community` repository.
   - Title the PR: `feat: add geckovision-risk-oracle skill`
   - In the PR description, mention that this is a submission for the Agentic Trading Contest.

5. **Register for the Contest:**
   Go to the [OKX Agentic Trading Contest page](https://web3.okx.com/boost/trading-competition/agentic-trading) and ensure you have clicked "Join competition" and submitted any required forms for the Skills track.

## Why This Will Win
The judges are looking for skills that make agents *better traders*. While everyone else is building "buy the dip" or "copy trade" skills, you are building the **safety layer** that prevents those other skills from draining wallets. It perfectly aligns with OKX's goal of making agentic trading safe for retail users.
