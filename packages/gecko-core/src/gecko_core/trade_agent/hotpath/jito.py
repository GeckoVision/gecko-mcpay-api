"""Jito bundle / MEV fingerprints for the Launch Firewall.

Source: Jito low-latency docs (docs.jito.wtf/lowlatencytxnsend). Two facts we
encode here, both pure + offline:

* **Tip accounts** — a Jito bundle pays one of 8 fixed tip accounts. A
  transaction that transfers to ANY of these is, by construction, a bundle
  submission → automated. This is the single highest-precision "this is a bot,
  not a human" tell (humans don't hand-build Jito bundles). It feeds the
  ``jito_bundle_snipe`` attack pattern once the parsed-tx ingest path lands
  (the vault-reserve path can't see the tip transfer; this is account-key level).

* **dontfront** — adding a read-only account whose pubkey starts with
  ``jitodontfront`` makes the block engine REJECT any bundle containing that tx
  unless the tx is at index 0 (it does NOT reorder you to the front — the bundle
  is simply invalid otherwise), so the tx can't be front-run. This is a
  *send-side mitigation* an issuer/agent applies to its own swap; we can also
  DETECT whether a tx is protected.

Hotpath-clean: stdlib only. Functions take the transaction's account-key strings
(from a parsed tx) — no I/O. The tip-account set can drift; the canonical live
list is ``getTipAccounts`` (kept here as the offline default + smoke baseline).
"""

from __future__ import annotations

from collections.abc import Iterable

# The 8 canonical Jito tip accounts (docs.jito.wtf). Verify against the live
# getTipAccounts endpoint before trusting in prod — kept here as the offline
# default and the smoke baseline.
JITO_TIP_ACCOUNTS: frozenset[str] = frozenset(
    {
        "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
        "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
        "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
        "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
        "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
        "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
        "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
    }
)

# Any pubkey starting with this prefix in a tx triggers Jito's anti-front rule.
JITO_DONTFRONT_PREFIX = "jitodontfront"


def is_jito_bundle_tx(account_keys: Iterable[str]) -> bool:
    """True if the tx pays a Jito tip account — i.e. it's a bundle submission.

    The highest-precision automation tell: a buy in a Jito bundle is categorically
    a bot, not a human. ``account_keys`` is the tx's account-key list (parsed-tx
    path); we don't need to decode the transfer amount, only its presence.
    """
    return any(k in JITO_TIP_ACCOUNTS for k in account_keys)


def has_dontfront_guard(account_keys: Iterable[str]) -> bool:
    """True if the tx carries a ``jitodontfront…`` account (front-run protected).

    Lets us tell an issuer/agent whether their swap is sandwich-protected, and
    distinguishes a defended tx from an exposed one.
    """
    return any(isinstance(k, str) and k.startswith(JITO_DONTFRONT_PREFIX) for k in account_keys)


__all__ = [
    "JITO_DONTFRONT_PREFIX",
    "JITO_TIP_ACCOUNTS",
    "has_dontfront_guard",
    "is_jito_bundle_tx",
]
