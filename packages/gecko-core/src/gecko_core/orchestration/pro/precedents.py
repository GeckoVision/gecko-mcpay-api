"""Render Gecko Flywheel precedents into a debate-context block.

S2X-06 surfaces precedents to the 5 agents in the opening prompt. The block
is intentionally compact (one line per precedent) because the analyst is
already on a tight context budget and we just need the agents to *see* the
prior verdicts — they'll re-raise specifics if they matter.

The empty-state branch ("No prior precedents found.") is deliberate: an
empty corpus is itself signal — the agents should know they're evaluating a
category Gecko has not seen before. Rendering nothing would let the agents
silently treat the absence as "no constraint."

S9-PRECEDENT-01 — precedents are now grouped by outcome (shipped / killed /
unknown) before rendering. The critic + judge use the outcome counts as a
prior on the verdict pipeline. The grouping is *additive*: each precedent
still surfaces its `[VERDICT]` tag (what the panel said) AND now its outcome
(what happened). Until the auto-labeling job lands in Sprint 10, every row
renders as `unknown`, which is correct (we genuinely don't know yet).
"""

from __future__ import annotations

from gecko_core.sessions.store import GeckoPrecedent, PrecedentOutcome

_BLOCK_HEADER = "Prior similar ideas Gecko evaluated:"
_EMPTY_LINE = "No prior precedents found."
_SUMMARY_CHAR_CAP = 240  # one line per precedent — truncate aggressively
# Cap each outcome group's rendered text so an over-eager 'unknown' bucket
# can't crowd out the (smaller, but more signal-rich) shipped / killed
# buckets. The total budget across all three groups roughly matches the
# pre-S9 unsorted-list budget.
_PER_GROUP_CHAR_CAP = 1200

# Order matters — strongest signal first so a token-truncated render keeps
# the most decision-relevant groups.
_OUTCOME_ORDER: tuple[PrecedentOutcome, ...] = ("shipped", "killed", "unknown")


def _one_line_summary(text: str) -> str:
    """Collapse multi-line summaries to a single line, capped to keep the block small."""
    flat = " ".join(text.split())
    if len(flat) > _SUMMARY_CHAR_CAP:
        return flat[: _SUMMARY_CHAR_CAP - 1].rstrip() + "…"
    return flat


def group_precedents_by_outcome(
    precedents: list[GeckoPrecedent],
) -> dict[PrecedentOutcome, list[GeckoPrecedent]]:
    """Bucket precedents into shipped / killed / unknown.

    Stable within each bucket — the input order (similarity desc, set by the
    retrieval RPC) is preserved so the highest-similarity rows render first
    inside their group. Returns all three keys even when a group is empty so
    callers can do unconditional lookups.
    """
    grouped: dict[PrecedentOutcome, list[GeckoPrecedent]] = {
        "shipped": [],
        "killed": [],
        "unknown": [],
    }
    for p in precedents:
        # Defensive: if a future migration adds a fourth label and we read it
        # back before the code knows about it, fall through to 'unknown'
        # rather than KeyError mid-debate.
        bucket = p.outcome if p.outcome in grouped else "unknown"
        grouped[bucket].append(p)
    return grouped


def _render_one(p: GeckoPrecedent) -> str:
    verdict_tag = p.verdict.upper()
    summary = _one_line_summary(p.idea_summary)
    sim = f" (sim={p.similarity:.2f})" if p.similarity is not None else ""
    return f"- [{verdict_tag}] {summary}{sim}"


def _render_group(label: PrecedentOutcome, items: list[GeckoPrecedent]) -> list[str]:
    """Render one outcome bucket, capped to `_PER_GROUP_CHAR_CAP`.

    The cap is enforced at line granularity (we never truncate mid-line) so
    the agents always see well-formed bullets. Surplus rows surface as a
    `… +N more` footer so the agents know the bucket is larger than what
    they're seeing.
    """
    header = f"{label.upper()}:"
    if not items:
        return [header, "  - (none)"]

    out = [header]
    used = 0
    rendered = 0
    for p in items:
        line = "  " + _render_one(p)
        if used + len(line) + 1 > _PER_GROUP_CHAR_CAP:
            break
        out.append(line)
        used += len(line) + 1
        rendered += 1
    if rendered < len(items):
        out.append(f"  - … +{len(items) - rendered} more")
    return out


def render_precedent_block(precedents: list[GeckoPrecedent]) -> str:
    """Return a compact, outcome-grouped block describing prior precedents.

    Output shape (S9-PRECEDENT-01)::

        Prior similar ideas Gecko evaluated:
        Precedents: 1 SHIPPED, 2 KILLED, 4 UNKNOWN
        SHIPPED:
          - [SHIP] short summary (sim=0.84)
        KILLED:
          - [KILL] short summary (sim=0.81)
          - [KILL] short summary (sim=0.79)
        UNKNOWN:
          - [SHIP] short summary (sim=0.77)
          - …

    Or, when ``precedents`` is empty::

        Prior similar ideas Gecko evaluated:
        - No prior precedents found.

    The summary line ("Precedents: X SHIPPED, Y KILLED, Z UNKNOWN") is the
    line the critic/judge prompts pattern-match on — keep it stable.
    """
    if not precedents:
        return f"{_BLOCK_HEADER}\n- {_EMPTY_LINE}"

    grouped = group_precedents_by_outcome(precedents)
    counts = ", ".join(f"{len(grouped[k])} {k.upper()}" for k in _OUTCOME_ORDER)
    lines: list[str] = [_BLOCK_HEADER, f"Precedents: {counts}"]
    for outcome in _OUTCOME_ORDER:
        items = grouped[outcome]
        if not items:
            # Skip empty buckets in the rendered output — the count line
            # above already declared them, no need to spend tokens on
            # `(none)` placeholders for every group.
            continue
        lines.extend(_render_group(outcome, items))
    return "\n".join(lines)


__all__ = ["group_precedents_by_outcome", "render_precedent_block"]
