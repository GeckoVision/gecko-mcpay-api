-- 20260516120000_telemetry_events.sql
-- Purpose: capture top-of-funnel install + register telemetry. Today the
--          only signal the platform emits is a `sessions` row, created
--          AFTER a successful tool call — people who fail to install (or
--          never call a tool) produce zero signal. This table records
--          install_started / install_ok / install_error / register so the
--          founder has an install-success rate and a defensible
--          "how many users / wallets" answer for investors.
-- Reversible: yes (drops the new table — pure observability, no business
--             data the rest of the codebase depends on).
-- Touches: new table `telemetry_events`. No existing rows changed.
-- Related: gecko_core.telemetry.store (record_event / telemetry_summary);
--          POST /events in gecko-api.

CREATE TABLE IF NOT EXISTS telemetry_events (
  id              UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
  event_type      TEXT NOT NULL,
  wallet_address  TEXT,
  email           TEXT,
  installer_tag   TEXT,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- event_type is INTENTIONALLY free-text — NO CHECK constraint. Telemetry
-- taxonomies evolve fast and we do not want a schema migration per new
-- event type. The known values live in a Python constant instead:
--   gecko_core.telemetry.store.KNOWN_TELEMETRY_EVENTS
-- (currently install_started / install_ok / install_error / register).
-- Unknown values are accepted; the writer logs a warning but still inserts.

-- Read pattern A: telemetry_summary() rolls up counts per event_type over
-- a time window — funnel + install-success rate.
CREATE INDEX IF NOT EXISTS telemetry_events_type_created_at_idx
  ON telemetry_events (event_type, created_at DESC);

-- Read pattern B: distinct registered-wallet count. Partial index keeps it
-- small — most install_started rows arrive before a wallet exists.
CREATE INDEX IF NOT EXISTS telemetry_events_wallet_idx
  ON telemetry_events (wallet_address)
  WHERE wallet_address IS NOT NULL;

-- Service-role only. `email` is PII and `wallet_address` is user-identifying
-- — neither may ever reach the anon key / gecko-mcpay-app surface. RLS is
-- enabled with an explicit deny-all policy for `anon`, matching the
-- bazaar_spend_ledger pattern. The write path is POST /events in gecko-api,
-- which uses the service-role client; the anon key is locked out entirely.
ALTER TABLE telemetry_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS telemetry_events_no_anon ON telemetry_events;
CREATE POLICY telemetry_events_no_anon
  ON telemetry_events
  FOR ALL
  TO anon
  USING (false)
  WITH CHECK (false);

COMMENT ON TABLE telemetry_events IS
  'S33-#73 — top-of-funnel install + register telemetry. event_type is '
  'free-text by design (no CHECK); known values live in '
  'gecko_core.telemetry.store.KNOWN_TELEMETRY_EVENTS. Service-role only — '
  'email is PII; never expose to anon / web app.';
COMMENT ON COLUMN telemetry_events.event_type IS
  'Free-text. Known values: install_started, install_ok, install_error, '
  'register. New types tolerated without a migration.';
COMMENT ON COLUMN telemetry_events.email IS
  'PII. Service-role read only. telemetry_summary() exposes a COUNT, never '
  'the values.';
