# Phase B5 v1 — Per-project vaults (shipped)

v1 of "per-project vaults": named, budgeted slices of a single
frames.ag main wallet. Targets the Shipathon. v2 (Privy direct wallets,
cryptographic isolation) is post-Shipathon and not in this PR.

## What shipped

- `gecko project init <name> --budget <USD>` — creates a row in `projects`
  via `SessionStore.create_project` and writes `<cwd>/.gecko/project.json`.
- `gecko project list` — Rich table of all projects for the current
  frames.ag user with budget / spent / remaining / sessions count.
- `gecko project budget <name> [--set <USD>]` — show or update budget.
- `gecko project show <name>` — id, budget, spent, last 5 sessions.
- `gecko project policy <name>` — read-through to the per-wallet
  frames.ag policy (`max_per_tx_usd`).
- `bb research --project <uuid|name>` flag plus auto-detection of
  `<cwd>/.gecko/project.json`.
- MCP `gecko_research` tool gains an optional `project_id` argument.
- `GeckoAPIClient.research(..., project_id=, frames_username=, budget_usd=,
  estimated_cost_usd=)` — passes project context in the POST body and runs
  a best-effort client-side budget pre-flight via the new free endpoint.
- `POST /research` accepts `project_id` + `frames_username` and calls
  `SessionStore.set_session_project(session_id, project_id,
  paid_from_wallet_address="<frames_username>:main")` — the
  `:main` suffix is the v1 audit marker; v2 will replace it with the
  per-project Privy wallet address.
- `GET /sessions/spent-by-project/{project_id}` — free endpoint returning
  `{project_id, total_spent_usd, sessions_count}`.
- Tests: `tests/cli/test_project.py`, extensions to
  `tests/api/test_middleware.py` and `tests/mcp/test_api_client.py`.

## What we did NOT do (v1 honesty markers)

- **No on-chain isolation per project.** Every paid call still flows
  from the user's frames.ag main wallet. Two projects from the same user
  share spend authority — the only thing separating them is a logical
  budget bucket plus client-side enforcement.
- **Budget pre-flight is client-side only.** A determined user editing
  their own `gecko-mcp` install can bypass it. The server-side ceiling
  is frames.ag's per-wallet `max_per_tx_usd` policy, not per-project.
  This is documented inline in `api_client._preflight_budget_check` and
  in the user-facing `gecko project init` output.
- **No per-project policy mutation.** `gecko project policy` is
  read-only; it surfaces the per-wallet policy. Changing
  `max_per_tx_usd` is still done via `gecko-mcp wallet policy`.
- **No Privy code.** v2 lives in a separate migration: replace
  `wallet_address: null` / `paid_from_wallet_address: "<u>:main"` with
  the Privy-managed wallet, delete the pre-flight check (the wallet
  itself becomes the ceiling). The `gecko project` UX surface is
  identical between v1 and v2 — only the wallet plumbing changes.
