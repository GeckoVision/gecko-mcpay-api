# Parked PRs — backlog

Stale open PRs closed to clean up the active list, captured here so the intent
isn't lost. Each branch is preserved (NOT deleted) — revive by reopening the PR
or rebasing the branch onto `main`.

> Closed during the 2026-06-18 repo reorg. Both predate ~6 weeks of `main`
> movement and both touch `.github/workflows/release.yml`, which has since
> evolved — so each needs a rebase + a fresh look before merge, not a blind merge.

---

## PR #8 — `ci(release): dispatch installer-version bump to gecko-claude on tag`
- **Branch:** `feat/gc-03-installer-version-dispatch`
- **Opened:** 2026-05-09 · **Touches:** `.github/workflows/release.yml`
- **Intent:** on a release tag, fire a cross-repo dispatch that bumps the
  installer version in `gecko-claude` (keeps the public `install.sh` version in
  lockstep with API releases).
- **Why parked:** cross-repo release automation is not on the critical path
  while the product is pre-launch; `release.yml` has changed since, so it needs
  a rebase. Revisit when the release cadence to `gecko-claude` is formalized.
- **Revive:** reopen #8 → rebase onto `main` → reconcile `release.yml` → verify
  the dispatch token/permissions against the current workflow.

## PR #10 — `docs: cite pay.sh sandbox parity + snapshot catalog for S20-PAYSH`
- **Branch:** `docs/pay-sh-sandbox-and-wallet-pattern`
- **Opened:** 2026-05-09 · **Touches:** `.github/workflows/release.yml`,
  `docs/demo/trade-oracle-stub-quickstart.md`, `docs/research/paysh/{agent-skills-index.json, catalog.json, homepage.md}`
- **Intent:** snapshot the pay.sh (Solana Foundation x402 CLI/MCP) catalog +
  sandbox-parity notes and the trade-oracle stub quickstart, for the S20 pay.sh
  integration angle.
- **Why parked:** the pay.sh integration is a distribution-channel bet, not the
  current Launch-Firewall focus; the catalog snapshot is ~6 weeks old and would
  need refreshing against the live pay.sh catalog before it's useful again.
- **Revive:** reopen #10 → re-pull the current pay.sh catalog → drop the stray
  `release.yml` hunk (unrelated to the docs) → rebase onto `main`.

---

When a parked item is revived and merged, delete its row here.
