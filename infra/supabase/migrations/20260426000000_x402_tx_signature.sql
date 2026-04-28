-- 20260426000000_x402_tx_signature.sql
-- Purpose: record the on-chain Solana tx signature returned by the x402 facilitator
--          after a successful settle, so live mode can correlate sessions with
--          explorer.solana.com transactions for the demo and refund/audit flows.
-- Reversible: yes (column is nullable and idempotent additions only).
-- Touches: table `sessions`.

ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS x402_tx_signature TEXT;

-- Partial index — only non-null signatures are interesting for lookup, and
-- stub mode emits synthetic signatures we don't want bloating the index.
CREATE INDEX IF NOT EXISTS sessions_x402_tx_signature_idx
  ON sessions (x402_tx_signature)
  WHERE x402_tx_signature IS NOT NULL;
