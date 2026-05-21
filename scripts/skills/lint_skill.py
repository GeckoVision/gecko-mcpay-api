#!/usr/bin/env python3
"""Skill self-lint — validate a Gecko skill against the OKX agent-skills
REVIEWING.md rubric. Pure-Python, no LLM, no external deps. Fail-closed
(exit 1 on any gate failure) so it can run as a CI gate before publishing.

Usage:
    python3 scripts/skills/lint_skill.py <path-to-skill-dir>

Checks (from okx/agent-skills REVIEWING.md):
  1. Frontmatter has `---` delimiters; name/description/triggers/dependencies parse
  2. description is 80-150 words (always-in-context, used for routing)
  3. SKILL.md < 500 lines (gate here; rubric frames it as a guideline)
  4. Standard structure (SKILL.md exists; scripts/ references/ assets/ are guideline WARNs)
  5. No phantom tool references — every okx-* skill referenced is real
  6. examples/*.md JSON code blocks parse
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The real OnchainOS skill set (github.com/okx/onchainos-skills/skills).
KNOWN_OKX_SKILLS = {
    "okx-a2a-payment", "okx-agentic-wallet", "okx-agent-payments-protocol",
    "okx-audit-log", "okx-dapp-discovery", "okx-defi-invest", "okx-defi-portfolio",
    "okx-dex-bridge", "okx-dex-market", "okx-dex-signal", "okx-dex-social",
    "okx-dex-strategy", "okx-dex-swap", "okx-dex-token", "okx-dex-trenches",
    "okx-dex-ws", "okx-growth-competition", "okx-how-to-play",
    "okx-onchain-gateway", "okx-security", "okx-wallet-portfolio", "okx-x402-payment",
}


class Report:
    def __init__(self) -> None:
        self.failed = False

    def gate(self, ok: bool, label: str, detail: str = "") -> None:
        tag = "PASS" if ok else "FAIL"
        if not ok:
            self.failed = True
        print(f"  {tag}  {label}" + (f" — {detail}" if detail else ""))

    def warn(self, label: str, detail: str = "") -> None:
        print(f"  WARN  {label}" + (f" — {detail}" if detail else ""))


def _parse_frontmatter(text: str) -> dict | None:
    """Return a shallow dict of top-level frontmatter keys, or None if no
    `---`-delimited block. Block-list values become Python lists."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return None
    body = m.group(1)
    out: dict[str, object] = {}
    cur_key: str | None = None
    for line in body.splitlines():
        if re.match(r"^\s*-\s+", line) and cur_key:  # block-list item
            out.setdefault(cur_key, [])
            if isinstance(out[cur_key], list):
                out[cur_key].append(re.sub(r"^\s*-\s+", "", line).strip().strip('"'))
            continue
        m2 = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if m2:
            key, val = m2.group(1), m2.group(2).strip()
            cur_key = key
            if val == "" or val == "[]":
                out[key] = []
            elif val.startswith("[") and val.endswith("]"):
                out[key] = [v.strip().strip('"') for v in val[1:-1].split(",") if v.strip()]
            else:
                out[key] = val.strip('"')
    return out


def lint(skill_dir: Path) -> int:
    print(f"Skill lint: {skill_dir}")
    print("=" * 60)
    r = Report()

    skill_md = skill_dir / "SKILL.md"
    r.gate(skill_md.exists(), "Check 4: SKILL.md exists")
    if not skill_md.exists():
        print("=" * 60)
        print("RESULT: FAIL (no SKILL.md)")
        return 1

    text = skill_md.read_text(encoding="utf-8")

    # Check 1 — frontmatter
    fm = _parse_frontmatter(text)
    r.gate(
        fm is not None and all(k in fm for k in ("name", "description", "triggers", "dependencies")),
        "Check 1: frontmatter parses name/description/triggers/dependencies",
        "" if fm else "no --- delimited frontmatter",
    )
    fm = fm or {}

    # Check 2 — description 80-150 words
    desc = str(fm.get("description", ""))
    wc = len(desc.split())
    r.gate(80 <= wc <= 150, "Check 2: description is 80-150 words", f"{wc} words")

    # Check 3 — under 500 lines
    nlines = text.count("\n") + 1
    r.gate(nlines < 500, "Check 3: SKILL.md under 500 lines", f"{nlines} lines")

    # Check 4 — standard dirs (guideline WARNs)
    for d in ("scripts", "references", "assets"):
        if not (skill_dir / d).is_dir():
            r.warn(f"Check 4: {d}/ present (guideline)", "absent — guideline, not a gate")

    # Check 5 — no phantom OKX skill references
    # Scan only the body (after frontmatter) so the skill's own `name:` line
    # doesn't produce a false-positive match (e.g. gecko-okx-* → okx-*).
    deps = fm.get("dependencies", [])
    deps = deps if isinstance(deps, list) else [deps]
    fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.S)
    body_text = text[fm_match.end():] if fm_match else text
    body_refs = set(re.findall(r"\bokx-[a-z0-9-]+\b", body_text))
    referenced = {str(d).strip() for d in deps if str(d).strip()} | body_refs
    phantom = sorted(s for s in referenced if s.startswith("okx-") and s not in KNOWN_OKX_SKILLS)
    r.gate(not phantom, "Check 5: no phantom OKX skill references",
           f"unknown: {phantom}" if phantom else "")

    # Check 6 — examples JSON blocks parse
    examples = sorted((skill_dir / "examples").glob("*.md")) if (skill_dir / "examples").is_dir() else []
    json_blocks = 0
    bad_json = 0
    for ex in examples:
        for block in re.findall(r"```json\s*\n(.*?)```", ex.read_text(encoding="utf-8"), re.S):
            json_blocks += 1
            try:
                json.loads(block)
            except json.JSONDecodeError:
                bad_json += 1
    if examples:
        r.gate(bad_json == 0, "Check 6: examples JSON blocks parse",
               f"{json_blocks} block(s)" + (f", {bad_json} BAD" if bad_json else ""))

    print("=" * 60)
    if r.failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 lint_skill.py <skill-dir>", file=sys.stderr)
        sys.exit(2)
    sys.exit(lint(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
