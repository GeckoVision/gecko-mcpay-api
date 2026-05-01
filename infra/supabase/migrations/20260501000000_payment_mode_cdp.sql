-- 20260501000000_payment_mode_cdp.sql
-- Purpose: extend sessions.payment_mode CHECK constraint to allow 'cdp'
--          (Coinbase Developer Platform Facilitator on Base mainnet,
--          shipped in Sprint 12 Track A — `CDPX402Client`).
-- Reversible: yes (drops and recreates the constraint).
-- Touches: sessions table only; no data migration needed.
--
-- Background: 20260425000000_init.sql declared
--   CHECK (payment_mode IN ('stub', 'live', 'frames'))
-- Sprint 12 added 'cdp' to gecko_core.payments.x402_client.X402Mode but the
-- corresponding DB constraint was never updated, so writing a session with
-- payment_mode='cdp' fails with code 23514. This migration fixes that.

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_payment_mode_check;

ALTER TABLE sessions
  ADD CONSTRAINT sessions_payment_mode_check
  CHECK (payment_mode IN ('stub', 'live', 'frames', 'cdp'));
