-- ===========================================================================
-- 20260609010000_privy_grant_ids.sql
-- Prod-persistence prerequisite for enabling Privy (V1 Phase 2).
--
-- WHY: SupabaseGrantStore (gecko_core.wallets.supabase_grant_store) persists the
-- Privy (user -> wallet, policy, scope) mapping across processes so a
-- multi-process prod deploy doesn't lose grant state. The 20260607010000 remodel
-- created wallet_links + agent_grants but did NOT carry the Privy vendor IDs:
--   * the Privy wallet_id  (needed to attach policies / sign on the user's wallet)
--   * the Privy policy_id   (needed to rewrite rules on revoke — deny-all)
-- Both are vendor-side handles, NOT key material (non-custodial invariant #1).
--
-- ADDITIVE + nullable: existing rows are untouched; pre-Privy links/grants simply
-- carry NULL. Safe to apply with no downtime.
--
-- !! NOT auto-applied. The founder applies migrations to remote Supabase. This
--    migration MUST be applied BEFORE flipping GECKO_WALLET_PROVIDER to privy in
--    prod, or SupabaseGrantStore writes will fail on the missing columns.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- wallet_links.external_wallet_id — the Privy wallet handle for this link.
-- Nullable: stub / non-Privy providers leave it NULL.
-- ---------------------------------------------------------------------------
ALTER TABLE wallet_links
  ADD COLUMN IF NOT EXISTS external_wallet_id TEXT;

COMMENT ON COLUMN wallet_links.external_wallet_id IS
  'Vendor wallet handle (Privy wallet_id) for this user-owned wallet. '
  'NULL for stub / non-vendor links. NOT key material (non-custodial invariant #1). '
  'Written by gecko_core.wallets.supabase_grant_store.SupabaseGrantStore.';

-- ---------------------------------------------------------------------------
-- agent_grants.policy_id — the Privy policy handle backing this scope.
-- Nullable: a grant may exist before a policy is created/attached.
-- ---------------------------------------------------------------------------
ALTER TABLE agent_grants
  ADD COLUMN IF NOT EXISTS policy_id TEXT;

COMMENT ON COLUMN agent_grants.policy_id IS
  'Vendor policy handle (Privy policy_id) backing this scope. NULL before a '
  'policy is attached. revoke rewrites the policy rules to deny-all (the row is '
  'kept for audit). Written by '
  'gecko_core.wallets.supabase_grant_store.SupabaseGrantStore.';
