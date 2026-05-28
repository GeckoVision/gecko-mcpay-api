#!/usr/bin/env python3
"""gecko-honeypot-generator — adversarial inputs for Bento Guard validation.

For each token symbol the user owns, generate adversarial variants in 5 classes:
  A. ASCII typo (one-char insertion / substitution / deletion)
  B. Unicode lookalike (Cyrillic Р→P, Cyrillic Т→T, Greek Α→A, ...)
  C. Hidden/zero-width character injection (U+200B, U+200C, U+FEFF)
  D. Mint substitution (same symbol, different mint address)
  E. Contract-pattern honeypot specs (sell-disabled, tax-100%, etc; for
     synthetic-token deployment on devnet)

Output: list of {kind, symbol, raw_mint, attack, expected_block_reason} that
Bento Guard's pre-flight check should DENY. The catch rate across this corpus
is the joint product's empirical claim.
"""
from __future__ import annotations

import json
import os
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


AttackClass = Literal["typo", "unicode", "hidden_char", "mint_sub", "contract_pattern"]


@dataclass
class AdversarialInput:
    kind: AttackClass
    legitimate_symbol: str          # the symbol the user MEANT
    legitimate_mint: str            # the mint they meant to swap into
    attacker_symbol: str            # the variant that the user/agent sees
    attacker_mint: str | None       # what the attacker would route to (None for symbol-only attacks)
    description: str                # human-readable attack description
    expected_block_reason: str      # why Bento Guard SHOULD reject

    def to_dict(self) -> dict:
        d = asdict(self)
        # Visualize the difference between strings
        if self.legitimate_symbol != self.attacker_symbol:
            d["visual_collision_hint"] = (
                f"legit='{self.legitimate_symbol}' "
                f"attack='{self.attacker_symbol}' "
                f"codepoints={[hex(ord(c)) for c in self.attacker_symbol]}"
            )
        return d


# ── Class A: ASCII typo ────────────────────────────────────────────


def gen_typo(symbol: str, mint: str) -> list[AdversarialInput]:
    """One-char typo variants — insertion, substitution, deletion, transposition."""
    out: list[AdversarialInput] = []
    # Insertion: double a letter
    for i in range(len(symbol)):
        v = symbol[:i] + symbol[i] + symbol[i:]
        out.append(AdversarialInput(
            kind="typo", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=v, attacker_mint=None,
            description=f"insertion: doubled '{symbol[i]}' at position {i}",
            expected_block_reason=f"symbol '{v}' not in allowlist; lookalike of '{symbol}'",
        ))
    # Transposition: swap adjacent letters
    for i in range(len(symbol) - 1):
        v = symbol[:i] + symbol[i+1] + symbol[i] + symbol[i+2:]
        if v == symbol:
            continue
        out.append(AdversarialInput(
            kind="typo", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=v, attacker_mint=None,
            description=f"transposition: swapped chars at {i},{i+1}",
            expected_block_reason=f"symbol '{v}' not in allowlist; lookalike of '{symbol}'",
        ))
    # Deletion
    for i in range(len(symbol)):
        v = symbol[:i] + symbol[i+1:]
        out.append(AdversarialInput(
            kind="typo", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=v, attacker_mint=None,
            description=f"deletion: removed char at {i}",
            expected_block_reason=f"symbol '{v}' not in allowlist; lookalike of '{symbol}'",
        ))
    # Substitution to visually-similar ASCII
    sub_map = {
        "O": ["0", "Q"], "0": ["O"], "l": ["1", "I"], "I": ["1", "l"],
        "S": ["5"], "5": ["S"], "B": ["8"], "8": ["B"], "G": ["6"], "6": ["G"],
        "E": ["3"], "3": ["E"], "Z": ["2"], "2": ["Z"],
    }
    for i, c in enumerate(symbol):
        for sub in sub_map.get(c, []):
            v = symbol[:i] + sub + symbol[i+1:]
            out.append(AdversarialInput(
                kind="typo", legitimate_symbol=symbol, legitimate_mint=mint,
                attacker_symbol=v, attacker_mint=None,
                description=f"substitution: '{c}' → '{sub}' at position {i}",
                expected_block_reason=f"symbol '{v}' not in allowlist; visual-similar substitution",
            ))
    return out


# ── Class B: Unicode lookalike (cross-script) ──────────────────────


# Confusable-character map — same visual glyph, different codepoint
# Latin → Cyrillic / Greek / Math equivalents that render identically
CONFUSABLES = {
    "A": ["А", "Α"],  # Cyrillic А (U+0410), Greek Α (U+0391)
    "B": ["В", "Β"],  # Cyrillic В (U+0412), Greek Β (U+0392)
    "C": ["С", "Ϲ"],  # Cyrillic С (U+0421), Greek Ϲ (U+03F9)
    "E": ["Е", "Ε"],  # Cyrillic Е (U+0415), Greek Ε (U+0395)
    "H": ["Н", "Η"],  # Cyrillic Н (U+041D), Greek Η (U+0397)
    "I": ["І", "Ι"],  # Cyrillic І (U+0406), Greek Ι (U+0399)
    "K": ["К", "Κ"],
    "M": ["М", "Μ"],
    "N": ["Ν"],       # Greek N
    "O": ["О", "Ο"],
    "P": ["Р", "Ρ"],  # Cyrillic Р (U+0420), Greek Ρ (U+03A1)
    "S": ["Ѕ"],       # Cyrillic Ѕ (U+0405)
    "T": ["Т", "Τ"],  # Cyrillic Т (U+0422), Greek Τ (U+03A4)
    "X": ["Х", "Χ"],
    "Y": ["У", "Υ"],
}


def gen_unicode_lookalike(symbol: str, mint: str) -> list[AdversarialInput]:
    """One-char Cyrillic/Greek substitution that renders identically."""
    out: list[AdversarialInput] = []
    for i, c in enumerate(symbol.upper()):
        for sub in CONFUSABLES.get(c, []):
            v = symbol[:i] + sub + symbol[i+1:]
            scripts = unicodedata.name(sub, "").split()[0] if sub else "?"
            out.append(AdversarialInput(
                kind="unicode", legitimate_symbol=symbol, legitimate_mint=mint,
                attacker_symbol=v, attacker_mint=None,
                description=f"unicode lookalike: Latin '{c}' → {scripts} '{sub}' (U+{ord(sub):04X}) at pos {i}",
                expected_block_reason=f"non-ASCII codepoint U+{ord(sub):04X} in symbol — Cyrillic/Greek confusable",
            ))
    return out


# ── Class C: Hidden / zero-width character injection ───────────────


ZERO_WIDTH_CHARS = [
    ("​", "U+200B ZERO WIDTH SPACE"),
    ("‌", "U+200C ZERO WIDTH NON-JOINER"),
    ("‍", "U+200D ZERO WIDTH JOINER"),
    ("﻿", "U+FEFF ZERO WIDTH NO-BREAK SPACE (BOM)"),
    ("⁠", "U+2060 WORD JOINER"),
]


def gen_hidden_char(symbol: str, mint: str) -> list[AdversarialInput]:
    """Insert invisible characters in the middle, or as prefix/suffix."""
    out: list[AdversarialInput] = []
    for ch, name in ZERO_WIDTH_CHARS:
        # Insert in the middle
        mid = len(symbol) // 2
        v = symbol[:mid] + ch + symbol[mid:]
        out.append(AdversarialInput(
            kind="hidden_char", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=v, attacker_mint=None,
            description=f"injected {name} at position {mid}",
            expected_block_reason=f"hidden codepoint {name} in symbol — symbol-equivalence fails string match",
        ))
        # Prefix
        out.append(AdversarialInput(
            kind="hidden_char", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=ch + symbol, attacker_mint=None,
            description=f"injected {name} as prefix",
            expected_block_reason=f"hidden codepoint {name} — visible string matches but string match fails",
        ))
    return out


# ── Class D: Mint substitution ─────────────────────────────────────


def gen_mint_substitution(symbol: str, mint: str) -> list[AdversarialInput]:
    """Same symbol, different mint address. The MOST DANGEROUS class."""
    out: list[AdversarialInput] = []
    # Real attack: an SPL token deployed with the same symbol "PYTH" but a
    # different mint, hoping the bot's resolver returns the malicious one
    fake_mints = [
        # Plausible-looking but malicious mints (these are example synthetic addresses)
        "FakeNewMintForPYTH" + "1" * 20,  # padding to 32+ chars
        "ScamPYTHMintDeployedToday" + "2" * 8,
        "Malicious" + symbol + "Token" + "3" * 18,
    ]
    for fm in fake_mints:
        # Truncate/pad to valid Solana mint length (~44 chars base58)
        attacker_mint = fm[:44].ljust(44, "X")
        out.append(AdversarialInput(
            kind="mint_sub", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=symbol, attacker_mint=attacker_mint,
            description=f"symbol '{symbol}' but mint '{attacker_mint[:20]}...' instead of legitimate '{mint[:20]}...'",
            expected_block_reason=f"mint '{attacker_mint[:20]}...' does NOT match canonical '{mint[:20]}...' for symbol '{symbol}'",
        ))
    return out


# ── Class E: Contract-pattern honeypot specs ───────────────────────


CONTRACT_PATTERNS = [
    ("sell_disabled", "Buy succeeds but sell() reverts; classic rug holder-trap"),
    ("buy_tax_100", "100% buy tax — input goes entirely to contract owner"),
    ("sell_tax_99", "99% sell tax — exiting takes 99% of value"),
    ("blacklist_owner", "Owner has freeze() method that blacklists any address"),
    ("hidden_mint_authority", "Owner retains mint_to authority — infinite dilution"),
    ("transfer_pause", "Owner can pause all transfers, freezing positions"),
    ("liquidity_pull", "LP not locked; owner can drain liquidity at any time"),
    ("renounce_lie", "renounceOwnership() returned but proxy owner still has admin"),
    ("hidden_fee_modifier", "Setter that increases tax post-launch (rug after volume)"),
    ("blocklist_function", "Bot/contract maintains tx-blocklist; tx may fail mid-execution"),
]


def gen_contract_patterns(symbol: str, mint: str) -> list[AdversarialInput]:
    """Synthetic-token deploy specs — for devnet honeypot deployment."""
    out: list[AdversarialInput] = []
    for pattern, desc in CONTRACT_PATTERNS:
        out.append(AdversarialInput(
            kind="contract_pattern", legitimate_symbol=symbol, legitimate_mint=mint,
            attacker_symbol=f"FAKE-{symbol}-{pattern}",
            attacker_mint=f"DevnetHoneypot_{pattern}_{symbol}"[:44].ljust(44, "X"),
            description=f"contract honeypot pattern: {pattern}",
            expected_block_reason=f"contract pattern '{pattern}' detected: {desc}",
        ))
    return out


# ── Composite generator ────────────────────────────────────────────


def generate_corpus(symbol: str, mint: str) -> list[AdversarialInput]:
    """Full corpus for one legitimate (symbol, mint) pair."""
    return (
        gen_typo(symbol, mint)
        + gen_unicode_lookalike(symbol, mint)
        + gen_hidden_char(symbol, mint)
        + gen_mint_substitution(symbol, mint)
        + gen_contract_patterns(symbol, mint)
    )


# ── Verification: does our CURRENT bot catch these? ────────────────


def simulate_current_bot_check(adv: AdversarialInput, allowlist: dict[str, str]) -> tuple[bool, str]:
    """Simulate the bot's CURRENT check: hardcoded INSTRUMENTS lookup.

    Returns (catches, reason). Catches=True means the bot would safely refuse.
    """
    sym = adv.attacker_symbol
    mint = adv.attacker_mint
    # Exact symbol match against allowlist?
    if sym not in allowlist:
        return True, f"symbol '{sym}' not in INSTRUMENTS allowlist (CAUGHT)"
    # Symbol matches — but does mint also match?
    expected_mint = allowlist[sym]
    if mint is None:
        # No mint substitution — pure symbol-route attack
        # The bot would use the allowlist's mint, so this is SAFE
        return True, f"symbol '{sym}' in allowlist; bot would use {expected_mint[:20]}... (SAFE — mint hardcoded)"
    if mint != expected_mint:
        # Mint substitution — bot DOESN'T currently check this!
        return False, f"symbol '{sym}' matched, but mint '{mint[:20]}...' != expected '{expected_mint[:20]}...' (BYPASSED)"
    return True, f"symbol+mint exact match (legitimate)"


def main() -> int:
    # Real bot universe (post Setup C)
    universe = {
        "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
        "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        "RAY": "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
    }

    all_adv: list[AdversarialInput] = []
    for sym, mint in universe.items():
        all_adv.extend(generate_corpus(sym, mint))

    # Tally by class
    from collections import Counter
    by_class = Counter(a.kind for a in all_adv)
    print("=" * 80)
    print("GECKO HONEYPOT GENERATOR — adversarial corpus")
    print("=" * 80)
    print(f"\nUniverse: {list(universe.keys())} ({len(universe)} legitimate tokens)")
    print(f"Total adversarial inputs generated: {len(all_adv)}")
    print(f"\nBy attack class:")
    for k, v in by_class.most_common():
        print(f"  {k:<22s}  n={v}")
    print()

    # Run through CURRENT bot's check
    catches, bypasses = 0, 0
    bypass_examples: list[tuple[AdversarialInput, str]] = []
    for adv in all_adv:
        ok, reason = simulate_current_bot_check(adv, universe)
        if ok:
            catches += 1
        else:
            bypasses += 1
            bypass_examples.append((adv, reason))

    print(f"\nCurrent bot check (simulated):")
    print(f"  CAUGHT:    {catches}  ({100*catches/len(all_adv):.1f}%)")
    print(f"  BYPASSED:  {bypasses}  ({100*bypasses/len(all_adv):.1f}%)")
    print()

    if bypass_examples:
        print(f"=== Bypass examples (Bento Guard NEEDED) ===\n")
        for adv, reason in bypass_examples[:6]:
            print(f"  [{adv.kind}] {adv.description}")
            print(f"    bot decision: {reason}")
            print(f"    expected block: {adv.expected_block_reason}\n")

    # Save the corpus for Bento Guard to test against
    out_dir = Path(__file__).parent
    out_file = out_dir / "adversarial_corpus.json"
    out_file.write_text(json.dumps([a.to_dict() for a in all_adv], indent=2, ensure_ascii=False))
    print(f"Corpus saved to {out_file}")
    print(f"\nNext: pipe this corpus through Bento Guard's pre-flight SDK; expected catch rate = 100%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
