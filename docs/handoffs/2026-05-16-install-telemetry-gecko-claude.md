# Handoff → gecko-claude: wire install-funnel telemetry

**Date:** 2026-05-16
**From:** gecko-mcpay-api (S33-#73)
**To:** gecko-claude (owns `skill.md` + `install.sh`)

## Context

gecko-mcpay-api now exposes `POST /events` — an unauthenticated, rate-limited
telemetry endpoint backed by the `telemetry_events` table. It exists so the
founder can see the **install funnel**: how many people try to install, how
many succeed/fail, and how many become real users. Today there is zero signal
until a successful tool call — people who fail to install are invisible.

The endpoint + table are built on the API side. **The pings that feed it must
be fired from `install.sh` and the skill bootstrap in this (gecko-claude)
repo.** That is the work this handoff describes.

## Endpoint contract

```
POST https://api.geckovision.tech/events
Content-Type: application/json

{
  "event_type": "install_started" | "install_ok" | "install_error" | "register",
  "wallet_address": "<solana addr>"   // optional; only on `register`
  "email": "<user email>",            // optional; only on `register`, only if given
  "installer_tag": "skill-install-sh-v1",   // static marker — see below
  "metadata": { ... }                 // optional, small JSON (error text, OS, etc.)
}
```

- Unauthenticated (it must work before a wallet exists).
- Rate-limited (~30/min/IP) — fine for real installs.
- Returns `202 {"ok": true}`.

## What to add

### 1. `install.sh` — three pings (fire-and-forget)

**Telemetry must NEVER break or slow an install.** Every call is backgrounded
and failure-swallowed (`|| true`, short timeout, `&`).

At the very start of `install.sh`:
```bash
GECKO_EVENTS_URL="https://api.geckovision.tech/events"
INSTALLER_TAG="skill-install-sh-v1"
_gecko_ping() {
  curl -s -m 3 -X POST "$GECKO_EVENTS_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"event_type\":\"$1\",\"installer_tag\":\"$INSTALLER_TAG\",\"metadata\":$2}" \
    >/dev/null 2>&1 || true
}
_gecko_ping install_started '{}' &
```

On success (end of script):
```bash
_gecko_ping install_ok '{}' &
```

On failure (trap / error path):
```bash
_gecko_ping install_error "{\"step\":\"$FAILED_STEP\"}" &
```

`installer_tag` is a static string — **not a secret**. It is not auth; it just
marks "this came from our installer" so dumb internet scanners hitting `/events`
don't pollute the metrics. A per-version tag (`-v1`, `-v2`) also lets you slice
install success by installer version.

### 2. Skill bootstrap — the `register` event

After the user creates their frames.ag wallet during bootstrap, fire **one**
`register` event with the wallet address and (if the user provided it) email:

```bash
curl -s -m 3 -X POST "$GECKO_EVENTS_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"event_type\":\"register\",\"wallet_address\":\"$WALLET_ADDR\",\"email\":\"$USER_EMAIL\",\"installer_tag\":\"$INSTALLER_TAG\"}" \
  >/dev/null 2>&1 || true
```

**Email must stay optional.** If the user does not give an email, send the
`register` event with `wallet_address` only. Do NOT block the user from
proceeding to their first verdict to collect an email — that reintroduces the
friction `X402_MODE=stub` exists to avoid.

## Resulting investor metrics

Once the pings land, the API side answers (via `telemetry_summary()`):
- installs attempted = `count(install_started)`
- install success rate = `install_ok / install_started`
- failure breakdown = `install_error` grouped by `metadata.step`
- users = distinct `wallet_address` on `register` events
- transactions / usage = existing `sessions` table

## Blocking note

The `telemetry_events` table migration must be applied to remote Supabase
before `/events` works in production (founder-gated action). The skill-side
changes here can land in parallel — pings just 202 into a void until the
table exists, which is harmless.
