#!/usr/bin/env python3
"""Generate the PUBLIC Status page (Mintlify MDX) from docs/TRUTH_MAP.md.

The truth map is the *internal* test-backed inventory. This generator publishes
ONLY the `✅ live` rows — capabilities a passing automated test proves — and
strips everything internal:

  * the Proof column (no test-file paths ever reach the public surface),
  * the internal Notes,
  * every 🟡 partial / 🟢 pending / ⬜ planned row (the honest internal hedges
    stay internal).

The rigor IS the brand: we publish what's proven, nothing else.

    python scripts/gen_public_status.py                 # write status.mdx
    python scripts/gen_public_status.py -o path/status.mdx
    python scripts/gen_public_status.py --check         # exit 1 if stale vs TRUTH_MAP
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "docs", "TRUTH_MAP.md")
_DEFAULT_OUT = os.path.join(_ROOT, "status.mdx")

_LIVE = "✅"
# Drop any non-live status from the public page.
_NON_LIVE = ("🟢", "🟡", "⬜")

# A test path looks like `foo/bar_test.py` or `...py::case`. Used to strip the
# Proof column defensively even after splitting on `|`.
_TEST_RE = re.compile(r"[\w./-]+\.py(?:::[\w\[\]\-]+)?")
# Inline code spans / bold around capability names — keep the text, drop markup.
_CODE_RE = re.compile(r"`([^`]*)`")
_BOLD_RE = re.compile(r"\*\*([^*]*)\*\*")

# Public-facing section titles, keyed by a substring of the TRUTH_MAP `##` heading.
_SECTION_TITLES = {
    "control plane": "Control plane",
    "safety": "Safety & verification",
    "execution adapter": "Execution adapters",
    "profit vault": "Profit vault",
    "arena": "Arena",
    "rigor": "Rigor harness",
    "custody": "Custody & distribution",
}


def _public_section_title(heading: str) -> str:
    low = heading.lower()
    for key, title in _SECTION_TITLES.items():
        if key in low:
            return title
    # Fall back to the heading text minus any parenthetical / trailing markup.
    clean = re.sub(r"\(.*?\)", "", heading).strip()
    clean = _CODE_RE.sub(r"\1", clean)
    return clean.strip()


def _clean_capability(cell: str) -> str:
    """Turn a raw capability cell into clean prose: drop code/bold markup and
    any stray test path, collapse whitespace."""
    text = _BOLD_RE.sub(r"\1", cell)
    text = _CODE_RE.sub(r"\1", text)
    text = _TEST_RE.sub("", text)  # belt-and-suspenders: no test paths
    return re.sub(r"\s+", " ", text).strip()


def parse_live(text: str) -> list[tuple[str, list[str]]]:
    """Parse TRUTH_MAP markdown -> ordered [(section_title, [capabilities])].

    Only rows inside a *capability* table (header has both 'Status' and 'Proof')
    AND marked ✅ live are collected. The capability is taken from the first
    column only; Proof + Notes columns are discarded entirely.
    """
    sections: list[tuple[str, list[str]]] = []
    cur_heading: str | None = None
    in_cap = False

    for line in text.splitlines():
        if line.startswith("## "):
            cur_heading = line[3:].strip()
            in_cap = False
            continue

        s = line.strip()
        if not s.startswith("|"):
            in_cap = False
            continue
        if "Status" in line and "Proof" in line:
            in_cap = True  # capability-table header
            continue
        if set(s) <= {"|", "-", " ", ":"}:
            continue  # separator row
        if not in_cap or cur_heading is None:
            continue

        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2:
            continue
        capability, status = cells[0], cells[1]
        if _LIVE not in status or any(b in status for b in _NON_LIVE):
            continue

        cap = _clean_capability(capability)
        if not cap:
            continue

        title = _public_section_title(cur_heading)
        for existing_title, caps in sections:
            if existing_title == title:
                caps.append(cap)
                break
        else:
            sections.append((title, [cap]))

    return sections


def render(sections: list[tuple[str, list[str]]], *, today: str) -> str:
    total = sum(len(caps) for _, caps in sections)
    lines: list[str] = []
    lines.append("---")
    lines.append('title: "Status"')
    lines.append(
        'description: "What\'s live — every capability below is verified by automated tests in CI."'
    )
    lines.append("---")
    lines.append("")
    lines.append(
        "Every capability below is verified by automated tests in our CI pipeline. "
        "We publish what's proven — the rigor is the product."
    )
    lines.append("")
    lines.append(
        f"<Info>**{total} verified capabilities** across {len(sections)} areas. "
        f"This page is generated from our internal test-backed inventory.</Info>"
    )
    lines.append("")
    for title, caps in sections:
        lines.append(f"## {title}")
        lines.append("")
        for cap in caps:
            lines.append(f"- {cap}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Generated {today} from the test-backed capability inventory._")
    lines.append("")
    return "\n".join(lines)


def _read_map() -> str:
    if not os.path.exists(_MAP):
        print(f"FAIL: {_MAP} not found — refusing to fabricate a Status page.", file=sys.stderr)
        sys.exit(2)
    with open(_MAP, encoding="utf-8") as fh:
        return fh.read()


def _strip_generated_line(content: str) -> str:
    """Remove the volatile `_Generated <date>_` footer so --check compares only
    the substantive page body, not today's date."""
    return re.sub(r"_Generated [^_]*_\n?", "", content)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=_DEFAULT_OUT, help="output MDX path")
    ap.add_argument(
        "--check",
        action="store_true",
        help="exit nonzero if the existing page is stale vs TRUTH_MAP (CI gate)",
    )
    args = ap.parse_args(argv)

    text = _read_map()
    sections = parse_live(text)
    today = datetime.date.today().isoformat()
    rendered = render(sections, today=today)

    if args.check:
        if not os.path.exists(args.out):
            print(f"STALE: {args.out} does not exist; run the generator.", file=sys.stderr)
            return 1
        with open(args.out, encoding="utf-8") as fh:
            existing = fh.read()
        if _strip_generated_line(existing).strip() != _strip_generated_line(rendered).strip():
            print(
                f"STALE: {args.out} is out of date vs TRUTH_MAP — regenerate it.", file=sys.stderr
            )
            return 1
        print(f"OK: {args.out} is up to date.")
        return 0

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(rendered)
    total = sum(len(caps) for _, caps in sections)
    print(f"Wrote {args.out}: {total} live capabilities across {len(sections)} sections.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
