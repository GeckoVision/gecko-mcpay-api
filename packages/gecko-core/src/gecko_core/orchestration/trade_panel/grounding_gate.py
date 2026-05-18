"""S36-#106 — Numeric grounding-or-abstain gate (code-side, prompt-free).

The S36-WS1 hallucination diagnosis (``docs/eval/2026-05-18-s36-
hallucination-diagnosis.md``) found ``hallucination_score`` is the lone
S35 ship-gate blocker, and that the dominant failure mode is a harness
artifact: the rubric judge scores numeric grounding against a citation
*snippet* that was double-truncated, so a real, API-sourced figure the
panel cited was simply not visible to the judge.

S36-WS2 part 1 (number-first chunk renderers) + part 2 (reconciled
snippet caps) make the figure judge-visible. This module is part 3 — a
deterministic gate that closes the loop:

  - Two prior fixes did NOT bind. S29-#33's prompt addendum is on every
    voice but gpt-4o-mini does not obey instruction-style grounding
    prompts (``memory/feedback_prompt_iteration_plateau``). S31-#49's
    ``hall_validator`` was never merged AND scanned the *full* chunk
    text — so it would mark a claim "sourced" while the judge, seeing
    only the truncated snippet, still scores it a hallucination. The
    validator and the judge disagreed because they read different text.

  - This gate reads the **exact same text the judge reads**: the
    post-truncation ``Citation.snippet`` of the verdict's
    ``evidence_citations`` + ``framework_context``. A numeric claim
    that passes this gate passes the judge **by construction** — there
    is no text the judge can see that the gate cannot.

It is grounding-OR-abstain, not soft-redaction: an ungrounded numeric
claim is reported, and the caller may abstain (downgrade confidence /
mark the verdict degraded) rather than ship a number it cannot defend.
The gate never calls the model, never loops, never spends. stdlib +
panel models only.

Self-consistency invariant (the load-bearing property):

    judge_input_text(citation)  ==  gate_input_text(citation)  ==  citation.snippet

Keep that equality true and the gate cannot disagree with the judge.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from gecko_core.orchestration.trade_panel.models import (
    Citation,
    TradePanelVerdict,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Numeric-claim extraction — patterns ordered most-specific first so the
# longest span wins (``$1.5B`` beats a bare ``$1.5``). Span-masking in
# :func:`extract_numeric_claims` prevents a later pattern double-counting.
# ---------------------------------------------------------------------------

_DOLLAR_WITH_SUFFIX = re.compile(
    r"\$\s?\d+(?:[,.]\d+)*\s?(?:k|m|b|t|thousand|million|billion|trillion)\b",
    re.IGNORECASE,
)
_DOLLAR_PLAIN = re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_DOLLAR_SHORT = re.compile(r"\$\s?\d+(?:\.\d+)?")
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s?%")
# Number-with-magnitude-suffix but no $ — "600k SOL", "TVL of 949M".
_BARE_SUFFIX = re.compile(r"\b\d+(?:\.\d+)?\s?(?:k|m|b|t)\b", re.IGNORECASE)
# Precise decimals (funding rates, lamport SOL figures) and large integers.
_RAW_DECIMAL_PRECISE = re.compile(r"\b\d+\.\d{3,}\b")
_RAW_SCIENTIFIC = re.compile(r"\b\d+(?:\.\d+)?e[+-]?\d+\b", re.IGNORECASE)
_RAW_LARGE_INT = re.compile(r"\b\d{5,}\b")

# Years are common vocabulary, not financial claims — never gate them.
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dollar_suffix", _DOLLAR_WITH_SUFFIX),
    ("dollar_plain", _DOLLAR_PLAIN),
    ("percent", _PERCENT),
    ("scientific", _RAW_SCIENTIFIC),
    ("bare_suffix", _BARE_SUFFIX),
    ("dollar_short", _DOLLAR_SHORT),
    ("decimal_precise", _RAW_DECIMAL_PRECISE),
    ("large_int", _RAW_LARGE_INT),
]

# Numeric-value fuzzy tolerance (proportional). A claimed 7.42% grounds
# against a snippet's 7.4% — rounding the panel does when it paraphrases.
_FUZZY_TOLERANCE = 0.01  # 1%

_SUFFIX_SCALE: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "million": 1e6,
    "b": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}


@dataclass(frozen=True)
class NumericClaim:
    """A single numeric span extracted from verdict text."""

    raw: str
    kind: str
    surface: str  # e.g. "key_drivers" or "turn:fundamental_analyst"


@dataclass(frozen=True)
class GroundingReport:
    """Outcome of the grounding gate over one verdict."""

    claims_total: int
    grounded: list[NumericClaim] = field(default_factory=list)
    ungrounded: list[NumericClaim] = field(default_factory=list)
    abstained: bool = False

    @property
    def grounded_fraction(self) -> float:
        """Fraction of numeric claims grounded; 1.0 when there are none."""
        if self.claims_total == 0:
            return 1.0
        return len(self.grounded) / self.claims_total


def extract_numeric_claims(text: str, *, surface: str = "") -> list[NumericClaim]:
    """Extract numeric claims from one text blob.

    Walks patterns most-specific-first, masking each matched span so a
    later, looser pattern cannot re-count it. Years are dropped.
    """
    if not text:
        return []
    working = list(text)
    claims: list[NumericClaim] = []
    for kind, pat in _PATTERNS:
        for m in pat.finditer("".join(working)):
            raw = m.group(0).strip()
            if kind in {"large_int", "decimal_precise"} and _YEAR_RE.match(raw):
                continue
            claims.append(NumericClaim(raw=raw, kind=kind, surface=surface))
            for i in range(m.start(), m.end()):
                working[i] = " "
    return claims


def _to_value(raw: str) -> float | None:
    """Best-effort numeric coercion, ignoring $, commas and a trailing %.

    Returns ``None`` for spans that are not numerically comparable.
    """
    s = raw.strip().lower().replace(",", "").replace("$", "").replace(" ", "")
    s = s.rstrip("%")
    scale = 1.0
    for suffix, mult in _SUFFIX_SCALE.items():
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            scale = mult
            break
    try:
        return float(s) * scale
    except (ValueError, TypeError):
        return None


def _claim_in_text(claim: NumericClaim, text: str) -> bool:
    """True if ``claim`` is supported by ``text`` (substring or fuzzy-value).

    ``text`` is the citation SNIPPET — the exact text the rubric judge
    receives. Keep this the only text the gate ever reads, or the
    self-consistency invariant breaks.
    """
    if not text:
        return False
    raw = claim.raw
    lo = text.lower()
    if raw.lower() in lo:
        return True
    # Whitespace-insensitive substring ("$ 949 M" vs "$949M").
    compact_claim = re.sub(r"\s+", "", raw).lower()
    if compact_claim in re.sub(r"\s+", "", lo):
        return True
    claim_val = _to_value(raw)
    if claim_val is None or claim_val == 0:
        return False
    tolerance = abs(claim_val) * _FUZZY_TOLERANCE
    for cc in extract_numeric_claims(text, surface="snippet"):
        cv = _to_value(cc.raw)
        if cv is None:
            continue
        if abs(cv - claim_val) <= tolerance:
            return True
    return False


def _snippet_corpus(verdict: TradePanelVerdict) -> list[str]:
    """The exact citation-snippet texts the judge sees.

    Both verdict citation lists, snippet field only. NOT the full chunk
    dict — reading the full chunk is the S31-#49 bug that made the
    validator disagree with the judge (diagnosis Cause 2).
    """
    cites: list[Citation] = [
        *verdict.evidence_citations,
        *verdict.framework_context,
    ]
    return [c.snippet for c in cites if c.snippet]


def _verdict_surfaces(verdict: TradePanelVerdict) -> list[tuple[str, str]]:
    """Every text surface the gate scans, tagged with its origin."""
    out: list[tuple[str, str]] = []
    for d in verdict.key_drivers:
        out.append(("key_drivers", d))
    for q in verdict.blocker_questions:
        out.append(("blocker_questions", q))
    for t in verdict.turns:
        out.append((f"turn:{t.agent}", t.content))
    return out


def check_grounding(
    verdict: TradePanelVerdict,
    *,
    abstain_threshold: float = 0.5,
) -> GroundingReport:
    """Run the grounding gate over a verdict.

    Every numeric claim in the verdict's text surfaces is checked against
    the citation snippets — the SAME text the rubric judge scores. A claim
    is *grounded* iff its figure appears in (or fuzzy-matches a number in)
    at least one snippet.

    ``abstained`` is set when the grounded fraction falls at or below
    ``abstain_threshold`` — the signal for the caller to downgrade
    confidence / mark the verdict degraded rather than ship ungrounded
    figures. The gate itself never mutates the verdict and never spends.
    """
    snippets = _snippet_corpus(verdict)
    claims: list[NumericClaim] = []
    for surface, text in _verdict_surfaces(verdict):
        claims.extend(extract_numeric_claims(text, surface=surface))

    if not claims:
        return GroundingReport(claims_total=0, grounded=[], ungrounded=[], abstained=False)

    grounded: list[NumericClaim] = []
    ungrounded: list[NumericClaim] = []
    for claim in claims:
        if any(_claim_in_text(claim, s) for s in snippets):
            grounded.append(claim)
        else:
            ungrounded.append(claim)

    report = GroundingReport(
        claims_total=len(claims),
        grounded=grounded,
        ungrounded=ungrounded,
        abstained=False,
    )
    abstained = report.grounded_fraction <= abstain_threshold
    report = GroundingReport(
        claims_total=report.claims_total,
        grounded=grounded,
        ungrounded=ungrounded,
        abstained=abstained,
    )
    for u in ungrounded:
        _log.info(
            "grounding_gate.ungrounded surface=%s kind=%s raw=%r",
            u.surface,
            u.kind,
            u.raw,
        )
    _log.info(
        "grounding_gate.applied claims=%d grounded=%d ungrounded=%d "
        "grounded_fraction=%.2f abstained=%s",
        report.claims_total,
        len(grounded),
        len(ungrounded),
        report.grounded_fraction,
        report.abstained,
    )
    return report


def apply_grounding_gate(verdict: TradePanelVerdict) -> tuple[TradePanelVerdict, GroundingReport]:
    """Run the gate and abstain on the verdict when grounding is weak.

    Abstain action is deliberately conservative and verdict-shape-safe:
    when :func:`check_grounding` reports ``abstained``, the verdict's
    ``confidence`` is floored toward 0.0 by the ungrounded fraction and a
    blocker question is appended naming the ungrounded figures. The
    ``verdict`` literal (KILL/REFINE/BUILD) is NOT flipped — that is a
    panel decision, not a grounding-gate decision; the gate only signals
    "do not trust the numbers" via confidence + an explicit blocker.

    Returns the (possibly adjusted) verdict and the report. Pure: no
    model call, no DB, no env flag — runs unconditionally on the panel
    path so production and eval read identical behaviour.
    """
    report = check_grounding(verdict)
    if not report.abstained or not report.ungrounded:
        return verdict, report

    ungrounded_raws = sorted({u.raw for u in report.ungrounded})
    note = (
        "Grounding gate: the following figures are not confirmed by any "
        "cited snippet and should be treated as unverified — " + ", ".join(ungrounded_raws) + "."
    )
    # Confidence floored by the ungrounded fraction: a verdict half of
    # whose numbers are unsourced cannot keep its full confidence.
    penalty = 1.0 - report.grounded_fraction
    new_confidence = round(max(0.0, verdict.confidence * (1.0 - penalty)), 4)
    new_blockers = [*verdict.blocker_questions, note]
    adjusted = verdict.model_copy(
        update={"confidence": new_confidence, "blocker_questions": new_blockers}
    )
    _log.info(
        "grounding_gate.abstain confidence %.3f -> %.3f ungrounded=%d",
        verdict.confidence,
        new_confidence,
        len(report.ungrounded),
    )
    return adjusted, report


__all__ = [
    "GroundingReport",
    "NumericClaim",
    "apply_grounding_gate",
    "check_grounding",
    "extract_numeric_claims",
]
