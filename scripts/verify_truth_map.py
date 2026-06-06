#!/usr/bin/env python3
"""Verify docs/TRUTH_MAP.md — the test-backed honesty gate.

A capability marked `✅ live` or `🟢 pending` MUST cite a test that exists (and,
with --run, passes). If a "live" claim has no resolvable/passing test, this exits
non-zero. That's the whole point: the truth map cannot lie about what works.

    uv run python scripts/verify_truth_map.py          # existence check (fast, CI-safe)
    uv run python scripts/verify_truth_map.py --run     # also RUN the cited tests (strict)

Rows marked 🟡 partial / ⬜ planned are NOT enforced (they're the honest gaps).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MAP = os.path.join(_ROOT, "docs", "TRUTH_MAP.md")
_ENFORCED = ("✅", "🟢")
_SKIP = ("🟡", "⬜")
_TEST_RE = re.compile(r"[\w./-]+\.py(?:::[\w\[\]\-]+)?")


def _rows(text: str) -> list[str]:
    """Only rows inside a *capability* table (one whose header has a 'Proof' column).
    Skips the legend table + any other markdown table."""
    out, in_cap = [], False
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_cap = False  # left the table
            continue
        if "Status" in line and "Proof" in line:
            in_cap = True  # capability-table header
            continue
        if set(s) <= {"|", "-", " ", ":"}:
            continue  # separator
        if in_cap:
            out.append(line)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true", help="run the cited tests, not just check they exist")
    args = ap.parse_args()

    if not os.path.exists(_MAP):
        print(f"FAIL: {_MAP} not found")
        return 1
    text = open(_MAP).read()

    # ✅ live = hard-enforced (must exist on this branch). 🟢 pending = soft (its
    # test may live in an open PR not yet merged) → warn, don't fail.
    rows = [r for r in _rows(text) if not any(b in r for b in _SKIP)]
    hard = [r for r in rows if "✅" in r]
    soft = [r for r in rows if "🟢" in r and "✅" not in r]
    missing: list[tuple[str, str]] = []
    warns: list[tuple[str, str]] = []
    refs: set[str] = set()

    def _check(row: str, sink: list, collect: bool) -> None:
        cap = row.split("|")[1].strip() if len(row.split("|")) > 1 else row[:40]
        row_refs = [r for r in _TEST_RE.findall(row) if "tests/" in r or "/calibration/" in r]
        if not row_refs:
            sink.append((cap, "NO TEST CITED"))
            return
        for ref in row_refs:
            if not os.path.exists(os.path.join(_ROOT, ref.split("::")[0])):
                sink.append((cap, f"missing test file: {ref}"))
            elif collect:
                refs.add(ref)

    for r in hard:
        _check(r, missing, collect=True)
    for r in soft:
        _check(r, warns, collect=False)

    print(f"truth-map: {len(hard)} ✅ live · {len(soft)} 🟢 pending · {len(refs)} unique test refs")
    if warns:
        print(f"⚠️  {len(warns)} pending (in-PR, not enforced): " + "; ".join(f"{c}: {w}" for c, w in warns))
    if missing:
        print(f"\n❌ {len(missing)} VIOLATION(S) — a '✅ live' claim is unproven:")
        for cap, why in missing:
            print(f"   - {cap}: {why}")
        return 1
    print("✅ every ✅-live row cites an existing test.")

    if args.run:
        files = sorted({os.path.join(_ROOT, r.split("::")[0]) for r in refs})
        print(f"\nrunning {len(files)} cited test files (strict)…")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider"],
            cwd=os.path.join(_ROOT, "contest_bot"),
        )
        if proc.returncode != 0:
            print("\n❌ a cited test FAILED — a 'live' claim does not actually pass.")
            return 1
        print("\n✅ all cited tests pass. Truth map is honest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
