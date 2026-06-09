-- seed_founder_binding.sql
-- ---------------------------------------------------------------------------
-- Seed the founder's user -> agent ownership binding for the deployed hosted
-- agent, so the app can read `GET /v1/agent/state` for `hosted-setupc-001`
-- BEFORE the founder onboards through the UI.
--
-- NORMAL PATH is bind-on-grant: POST /v1/onboarding/grant writes the
-- user_agents row automatically (gecko_api.routes._bindings.bind_user_agent).
-- This script is the FALLBACK / first-boot seed for the single deployed agent.
--
-- WHY app_users is inserted first: user_agents.user_id is a FK to
-- app_users(id) (migration 20260607010000_supabase_remodel.sql). A binding
-- cannot exist without its owner row. As of this writing nothing in the
-- onboarding code creates app_users rows, so this seed creates both. (Tracked
-- follow-up: bind_user_agent must upsert app_users for the multi-user path.)
--
-- Derive :founder_user_id from the founder's wallet address — it must match
-- gecko_api.routes._session.user_id_for() exactly:
--     user_id = "u_" + sha256(wallet.encode()).hexdigest()[:16]   (raw bytes, no lowercasing)
-- Postgres equivalent (pgcrypto's digest()):
--     'u_' || substr(encode(digest('<WALLET_ADDRESS>', 'sha256'), 'hex'), 1, 16)
-- or compute it off-DB:
--     python -c "import hashlib,sys;print('u_'+hashlib.sha256(sys.argv[1].encode()).hexdigest()[:16])" <WALLET_ADDRESS>
--
-- Usage (do NOT hardcode a wallet in the repo — pass it in):
--     psql "$SUPABASE_DB_URL" \
--       -v founder_user_id="u_xxxxxxxxxxxxxxxx" \
--       -v agent_id="hosted-setupc-001" \
--       -v strategy="setup_c" \
--       -v profile="balanced" \
--       -f infra/supabase/scripts/seed_founder_binding.sql
--
-- Idempotent: safe to re-run. Updates the existing binding in place.
-- ---------------------------------------------------------------------------

\set ON_ERROR_STOP on

-- Defaults if the caller didn't pass -v (agent/strategy/profile only; the
-- user_id has no safe default and MUST be provided).
\if :{?agent_id}
\else
  \set agent_id 'hosted-setupc-001'
\endif
\if :{?strategy}
\else
  \set strategy 'setup_c'
\endif
\if :{?profile}
\else
  \set profile 'balanced'
\endif

\if :{?founder_user_id}
\else
  \echo '!! founder_user_id is required: -v founder_user_id="u_<first16 hex of sha256(wallet)>"'
  \quit
\endif

BEGIN;

-- 1. Owner row (FK target for user_agents.user_id).
INSERT INTO app_users (id)
VALUES (:'founder_user_id')
ON CONFLICT (id) DO NOTHING;

-- 2. The binding. ON CONFLICT targets the partial unique index
--    user_agents_agent_id_uidx (agent_id WHERE deleted_at IS NULL) — raw SQL
--    CAN name the partial predicate, unlike PostgREST's bare on_conflict.
INSERT INTO user_agents (user_id, agent_id, strategy, profile, status)
VALUES (:'founder_user_id', :'agent_id', :'strategy', :'profile', 'deployed')
ON CONFLICT (agent_id) WHERE deleted_at IS NULL
DO UPDATE SET
  user_id  = EXCLUDED.user_id,
  strategy = EXCLUDED.strategy,
  profile  = EXCLUDED.profile,
  status   = 'deployed';

COMMIT;

-- Verify (prints the seeded binding).
SELECT user_id, agent_id, strategy, profile, status
FROM user_agents
WHERE agent_id = :'agent_id' AND deleted_at IS NULL;
