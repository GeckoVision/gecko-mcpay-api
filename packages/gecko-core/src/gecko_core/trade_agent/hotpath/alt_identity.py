"""ALT-as-operator-identity — the deep MEV-anatomy vein (the "dive deep" frontier).

The standard way to cluster coordinated buyers is by **money flow**: who funded
whom (the common-funder / sybil graph, F4). Sophisticated operators defeat it by
re-funding wallets through fresh hops. But a sniper reuses its **execution rig**
even when it rotates wallets — and the sharpest fingerprint of that rig is the
**address-lookup-table (ALT)** the bot pre-warms to pack more accounts into its
transactions. Distinct "unrelated" buyers sharing the same custom ALT are the same
operator, *regardless of how their wallets were funded*. This clusters by shared
INFRASTRUCTURE, which survives funding laundering that funder-graphs miss.

Almost nobody instruments ALTs as identity (Solidus & co. cluster by flow), and
it's cheap from data we already parse (`addressTableLookups` on the parsed tx).
That intersection — high novelty × cheap-from-our-data — is why this is the vein
to own. Depth ladder: account-key → **ALT** → bundle-internal structure.

Pure + offline (stdlib only): falsifiable today against synthetic swaps (Pattern
B), live-wired when the parsed-tx (enhanced) stream lands.

**FP guard (mandatory, discharged at the live smoke):** public aggregator/router
ALTs (Jupiter etc.) are shared by EVERYONE routing through them — a shared *public*
ALT is not a coordination signal. :data:`PUBLIC_ALTS` is the allowlist of such
tables; it ships empty with a loud note and MUST be populated from real traffic
before the signal is trusted live, or legitimate Jupiter routers false-positive.
"""

from __future__ import annotations

# Known public / aggregator / router ALTs shared by unrelated users (NOT a
# coordination tell). SEED EMPTY — populate from the live smoke before trusting
# the shared-ALT signal in prod, else Jupiter/router traffic false-positives.
# (Pattern A: one canonical place; Pattern-E reachability discharge required.)
PUBLIC_ALTS: frozenset[str] = frozenset()

# A custom ALT shared by at least this many DISTINCT buyers = an operator cluster.
SHARED_ALT_MIN_BUYERS = 2


def shared_alt_buyers(
    buyer_alts: dict[str, set[str]],
    *,
    public_alts: frozenset[str] = PUBLIC_ALTS,
) -> int:
    """Count distinct buyers who share at least one NON-public ALT with another buyer.

    ``buyer_alts`` maps each buyer wallet → the set of ALT addresses its swaps used.
    A buyer is "clustered" if any of its (non-public) ALTs is also used by a
    different buyer. Returns the number of such clustered buyers (0 = no shared-rig
    coordination). Public/aggregator ALTs are excluded — they're shared by design.
    """
    # alt -> set of buyers that used it (public ALTs dropped)
    alt_to_buyers: dict[str, set[str]] = {}
    for buyer, alts in buyer_alts.items():
        for alt in alts:
            if alt in public_alts:
                continue
            alt_to_buyers.setdefault(alt, set()).add(buyer)

    clustered: set[str] = set()
    for buyers in alt_to_buyers.values():
        if len(buyers) >= SHARED_ALT_MIN_BUYERS:
            clustered.update(buyers)
    return len(clustered)


__all__ = ["PUBLIC_ALTS", "SHARED_ALT_MIN_BUYERS", "shared_alt_buyers"]
