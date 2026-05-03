"""Terminal rendering for the CLI. Owned by `product-designer`.

The reveal moment (Business Plan -> Validation Report -> PRD) is the demo's
emotional beat: each document gets its own Panel, separated by a labelled Rule,
with a numbered, deduped citations list at the bottom of each panel.

Style rules (from `.claude/agents/product-designer.md` and CLAUDE.md):
- Hierarchy via Rich box drawing, not emoji. No emojis at all (user preference).
- Color is meaning. We additionally use a per-document accent so the three
  panels read as distinct beats:
    Business Plan   -> "green"        (emerald: growth, the offer)
    Validation      -> "yellow"       (amber: scrutiny, evidence)
    PRD             -> "bright_blue"  (indigo: build, plan)
  These three accents map cleanly to Rich's standard 8-color palette, so they
  render predictably across terminals (no 256-color assumptions).
- Citations are trust mechanism, not decoration. Numbered, scannable, clickable
  via OSC-8 links when the terminal supports it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import TracebackType

from gecko_core.models import (
    PRD,
    AskResult,
    BusinessPlan,
    Citation,
    Competitor,
    Dissent,
    MarketLandscape,
    NextStep,
    NextStepsWithFalsifiers,
    PerVoiceReadout,
    RefinedIdea,
    ResearchResult,
    SourceCandidate,
    SourceInfo,
    SurvivingDissent,
    ValidationReport,
    Verdict,
    VoicePosition,
)
from rich.box import ROUNDED
from rich.console import Console, Group
from rich.padding import Padding
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# --- Palette (kept here so the choice is documented in one place) ----------
_BP_STYLE = "green"
_VR_STYLE = "yellow"
_PRD_STYLE = "bright_blue"
_HEADER_STYLE = "dim"
_META_STYLE = "dim"

# S11-VERDICT-01 / S17-TONE-01 — palette for the single-token verdict
# headline. PIVOT is the tightest call so it gets the highest-contrast
# warning hue; GO is the green light; REFINE is amber (between the two).
_VERDICT_STYLES: dict[Verdict, str] = {
    Verdict.PIVOT: "bold red",
    Verdict.REFINE: "bold yellow",
    Verdict.GO: "bold green",
}


def _console(console: Console | None) -> Console:
    return console if console is not None else Console()


# --- Citations -------------------------------------------------------------


def _dedup_citations(citations: list[Citation]) -> list[Citation]:
    """Dedup by (url, chunk_index); preserve first-seen order."""
    seen: set[tuple[str, int]] = set()
    out: list[Citation] = []
    for c in citations:
        key = (str(c.source_url), c.chunk_index)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _truncate_wallet(wallet: str) -> str:
    """4+4 truncation with middle ellipsis (e.g. ``9xKp…aF2Q``).

    Short wallets (<= 9 chars) are returned unchanged so we never
    accidentally inflate them with an ellipsis that adds characters.
    """
    if len(wallet) <= 9:
        return wallet
    return f"{wallet[:4]}…{wallet[-4:]}"


def _citations_renderable(citations: list[Citation], accent: str) -> Text | None:
    """Numbered citations block, clickable via OSC-8 hyperlinks where supported.

    S13-CITE-01: when a citation carries `creator_handle` / `creator_payout_usd`
    / `creator_wallet`, surface them on a dim sub-line under the URL line.
    Pre-Paragraph runs (all three fields None) render byte-identically to
    pre-S13 — no sub-line is emitted.
    """
    deduped = _dedup_citations(citations)
    if not deduped:
        return None
    body = Text()
    body.append("Sources\n", style=f"bold {accent}")
    for i, c in enumerate(deduped, start=1):
        url = str(c.source_url)
        body.append(f"[{i}] ", style=f"bold {accent}")
        # `link` style triggers OSC-8 hyperlinks; plain text fallback otherwise.
        body.append(url, style=f"link {url}")
        body.append(f"  chunk {c.chunk_index}", style=_META_STYLE)
        body.append(f"  (sim {c.similarity:.2f})", style=_META_STYLE)
        # S13-CITE-01 — creator attribution sub-line. Only emitted when at
        # least one creator field is populated. Format mirrors the product-
        # designer memo §2: `@handle · NNNN USDC paid · sol:XXXX…XXXX`.
        if c.creator_handle or c.creator_payout_usd is not None or c.creator_wallet:
            body.append("\n    ", style=_META_STYLE)
            sep = ""
            if c.creator_handle:
                body.append(f"@{c.creator_handle}", style=f"bold {accent}")
                sep = " · "
            if c.creator_payout_usd is not None:
                body.append(sep, style=_META_STYLE)
                body.append(f"${c.creator_payout_usd:.4f} paid", style=_META_STYLE)
                sep = " · "
            if c.creator_wallet:
                body.append(sep, style=_META_STYLE)
                body.append(_truncate_wallet(c.creator_wallet), style=_META_STYLE)
        if i < len(deduped):
            body.append("\n")
    return body


def _creator_payouts_footer(citations: list[Citation], accent: str) -> Text | None:
    """S13-CITE-01 — aggregate "Creator payouts" footer block.

    Returns ``None`` when no citation carries a non-null
    ``creator_payout_usd`` so pre-Paragraph runs render unchanged. When
    any payout is present, returns a single-line summary suitable for
    rendering at the bottom of a document panel:

        Creator payouts ......... $0.0150 (3 creators)
    """
    paying = [c for c in citations if c.creator_payout_usd is not None]
    if not paying:
        return None
    total = sum(c.creator_payout_usd or 0.0 for c in paying)
    # Distinct creator handles when present; fall back to citation count.
    handles = {c.creator_handle for c in paying if c.creator_handle}
    n = len(handles) if handles else len(paying)
    label = "creator" if n == 1 else "creators"
    t = Text()
    t.append("Creator payouts", style=f"bold {accent}")
    t.append(" ", style=_META_STYLE)
    t.append(f"${total:.4f}", style="default")
    t.append(f" ({n} {label})", style=_META_STYLE)
    return t


# --- Document body builders ------------------------------------------------


def _kv(label: str, value: str, accent: str) -> Text:
    t = Text()
    t.append(f"{label}\n", style=f"bold {accent}")
    t.append(value, style="default")
    return t


def _bullets(label: str, items: list[str], accent: str) -> Text:
    t = Text()
    t.append(f"{label}\n", style=f"bold {accent}")
    if not items:
        t.append("(none)", style=_META_STYLE)
        return t
    for i, item in enumerate(items):
        t.append("  - ", style=accent)
        t.append(item)
        if i < len(items) - 1:
            t.append("\n")
    return t


def _spacer() -> Text:
    return Text("")


def _business_plan_body(bp: BusinessPlan, accent: str) -> Group:
    parts: list[Text] = [
        _kv("Problem", bp.problem, accent),
        _spacer(),
        _kv("ICP", bp.icp, accent),
        _spacer(),
        _kv("Solution", bp.solution, accent),
        _spacer(),
        _kv("Market", bp.market, accent),
        _spacer(),
        _kv("Business model", bp.business_model, accent),
        _spacer(),
        _kv("Channels", bp.channels, accent),
        _spacer(),
        _bullets("Key risks", bp.risks, accent),
    ]
    cites = _citations_renderable(bp.citations, accent)
    if cites is not None:
        parts.append(_spacer())
        parts.append(cites)
    payouts = _creator_payouts_footer(bp.citations, accent)
    if payouts is not None:
        parts.append(_spacer())
        parts.append(payouts)
    return Group(*parts)


def _verdict_line(verdict: Verdict, gap_summary: str = "") -> Text:
    """S11-VERDICT-01 — the single-token founder-facing headline.

    Renders ``VERDICT ─────── PIVOT`` (or REFINE / GO) in the verdict's
    accent color. The typed gap_classification stays as a sub-line via
    ``_gap_line`` — verdict is the headline, gap is the evidence.
    """
    style = _VERDICT_STYLES[verdict]
    t = Text()
    t.append("VERDICT ", style=style)
    t.append("─" * 7, style="dim")
    t.append(" ", style=style)
    t.append(verdict.value, style=style)
    return t


def _gap_line(v: ValidationReport, accent: str) -> Text:
    """S9-VERDICT-01 — bold one-liner under the verdict surfacing the
    structured gap classification + summary. Renders even when the LLM only
    provided the label (no summary) so the taxonomy stays visible."""
    t = Text()
    t.append("Gap: ", style=f"bold {accent}")
    t.append(v.gap_classification, style="bold")
    summary = (v.gap_summary or "").strip()
    if summary:
        t.append(" — ", style=_META_STYLE)
        t.append(summary)
    return t


def _validation_body(v: ValidationReport, accent: str, *, verdict: Verdict | None = None) -> Group:
    parts: list[Text] = []
    if verdict is not None:
        # S11-VERDICT-01 — verdict headline first, then the typed gap as
        # the immediate sub-line (PIVOT + Gap: Full reads as a single
        # block: token + evidence on consecutive lines).
        parts.append(_verdict_line(verdict))
        parts.append(_spacer())
    parts.extend(
        [
            _gap_line(v, accent),
            _spacer(),
            _kv("Market size signal", v.market_size_signal, accent),
            _spacer(),
            _kv("Competitor analysis", v.competitor_analysis, accent),
            _spacer(),
            _kv("Demand evidence", v.demand_evidence, accent),
            _spacer(),
            _bullets("Risk flags", v.risk_flags, accent),
        ]
    )
    cites = _citations_renderable(v.citations, accent)
    if cites is not None:
        parts.append(_spacer())
        parts.append(cites)
    payouts = _creator_payouts_footer(v.citations, accent)
    if payouts is not None:
        parts.append(_spacer())
        parts.append(payouts)
    return Group(*parts)


def _prd_body(
    p: PRD,
    accent: str,
    *,
    gap: ValidationReport | None = None,
    verdict: Verdict | None = None,
) -> Group:
    parts: list[Text] = []
    if verdict is not None:
        # S11-VERDICT-01 — PRD header line 1 is the single-token verdict.
        # The thinking: the PRD is what the user pastes into Claude Code;
        # the verdict needs to be the first thing they (or their model)
        # see when they open it.
        parts.append(_verdict_line(verdict))
        parts.append(_spacer())
    parts.append(_bullets("V1 scope", p.v1_scope, accent))
    if gap is not None:
        # S9-VERDICT-01 — echo the gap classification under V1 scope so the
        # PRD output surfaces the same structured signal the validation panel
        # carries. One line, dimmed accent so it reads as metadata.
        parts.append(_spacer())
        parts.append(_gap_line(gap, accent))
    parts.append(_spacer())
    parts.extend(
        [
            _bullets("V2 scope", p.v2_scope, accent),
            _spacer(),
            _bullets("V3 scope", p.v3_scope, accent),
            _spacer(),
            _bullets("Acceptance criteria", p.acceptance_criteria, accent),
            _spacer(),
            _bullets("Non-functional", p.non_functional, accent),
            _spacer(),
            _bullets("Success metrics", p.success_metrics, accent),
        ]
    )
    cites = _citations_renderable(p.citations, accent)
    if cites is not None:
        parts.append(_spacer())
        parts.append(cites)
    payouts = _creator_payouts_footer(p.citations, accent)
    if payouts is not None:
        parts.append(_spacer())
        parts.append(payouts)
    return Group(*parts)


def _doc_panel(title: str, body: Group, accent: str) -> Panel:
    return Panel(
        body,
        title=Text(title, style=f"bold {accent}"),
        title_align="left",
        border_style=accent,
        box=ROUNDED,
        padding=(1, 2),
        expand=True,
    )


# --- Public renderers ------------------------------------------------------


# --- Demo output (v5.5) ----------------------------------------------------
#
# 7-section verdict-led layout per docs/design/2026-05-02-research-output-shape.md
# (reconciled to the AI/ML spec naming and current Verdict enum
# SHIP/REFINE/KILL — but our enum is GO/REFINE/PIVOT/KILL; spec mapped GO=green,
# REFINE=yellow, KILL=bright_red, PIVOT inherits the legacy red).

_DEMO_VERDICT_STYLES: dict[Verdict, str] = {
    Verdict.GO: "bold reverse green",
    Verdict.REFINE: "bold reverse yellow",
    Verdict.PIVOT: "bold reverse red",
    Verdict.KILL: "bold reverse bright_red",
}

_VOICE_DISPLAY_ORDER: tuple[str, ...] = (
    "analyst",
    "critic",
    "architect",
    "scoper",
    "judge",
)

# Map AG2 internal voice ids -> human-readable display names. Forward-compat
# with S21 program-judges: any name not in the map falls through unchanged
# (e.g. an injected `kuka_market_superteam_br` renders as that string).
_VOICE_DISPLAY_NAMES: dict[str, str] = {
    "analyst": "Analyst",
    "critic": "Critic",
    "architect": "Architect",
    "scoper": "Scoper",
    "judge": "Judge",
}


def _voice_display(name: str) -> str:
    return _VOICE_DISPLAY_NAMES.get(name, name)


def _truncate_line(s: str, width: int) -> str:
    s = s.replace("\n", " ").strip()
    if len(s) <= width:
        return s
    return s[: max(0, width - 1)].rstrip() + "…"


def _short_hash(result: ResearchResult) -> str:
    h = result.verdict_hash or ""
    return h[:12] if h else "unknown"


def _demo_header(result: ResearchResult, idea: str) -> Panel:
    style = _DEMO_VERDICT_STYLES.get(result.verdict, "bold reverse white")
    label = Text(f" {result.verdict.value} ", style=style)
    short = _short_hash(result)
    hash_text = Text(f"verdict@{short}", style="dim cyan")
    line1 = Text.assemble(label, "  ", hash_text)
    classification = getattr(result, "idea_classification", None)
    founder_posture = getattr(result, "founder_posture", None)
    lines: list[Text] = [line1]
    # S21-CALIBRATION-FOUNDER-POSTURE-01 — render both classifications on
    # the same row when either is present. Founder posture is additive;
    # the existing classification-only fixture path keeps rendering byte-
    # identically when founder_posture is None.
    if classification or founder_posture:
        segments: list[tuple[str, str]] = []
        if classification:
            segments.append(("Classification: ", "dim"))
            segments.append((classification, "bold"))
        if classification and founder_posture:
            segments.append(("  ·  ", "dim"))
        if founder_posture:
            segments.append(("Founder posture: ", "dim"))
            segments.append((founder_posture, "bold"))
        lines.append(Text.assemble(*segments))
    lines.append(Text(f"Idea: {_truncate_line(idea, 76)}"))
    body = Group(*lines)
    return Panel(body, title="Gecko Verdict", border_style="cyan", width=80)


def _voice_block(v: VoicePosition) -> Group:
    name_line = Text.assemble(("▸ ", "bright_green"), (_voice_display(v.name), "bold cyan"))
    if v.status == "silent":
        body = Text("    (silent — no contribution this round)", style="dim italic")
        return Group(name_line, body)
    position = v.position or "(no position recorded)"
    tension = v.tension or "(no pushback this round)"
    recommend = v.recommendation or "(no recommendation)"
    return Group(
        name_line,
        Text.assemble(("    Position:  ", "dim"), position),
        Text.assemble(("    Tension:   ", "dim"), tension),
        Text.assemble(("    Recommend: ", "dim"), recommend),
    )


def _voices_section(per_voice: PerVoiceReadout) -> Group:
    by_name: dict[str, VoicePosition] = {v.name: v for v in per_voice.voices}
    items: list[Group | Text | Padding] = [Text("▸ Voices", style="bold cyan"), Text("")]
    for name in _VOICE_DISPLAY_ORDER:
        v = by_name.get(name)
        if v is None:
            continue
        items.append(Padding(_voice_block(v), (0, 0, 1, 2)))
    return Group(*items)


def _transcript_section(summary: str) -> Group:
    return Group(
        Text("▸ Transcript", style="bold cyan"),
        Text(""),
        Padding(Text(summary), (0, 0, 1, 2)),
    )


def _landscape_section(landscape: MarketLandscape) -> Group:
    t = Table(show_header=True, header_style="bold cyan", border_style="dim", box=ROUNDED)
    t.add_column("Competitor", width=16, overflow="fold")
    t.add_column("Their thing", width=30, overflow="fold")
    t.add_column("Why we're different", width=28, overflow="fold")
    competitors: list[Competitor] = list(landscape.competitors[:5])
    for comp in competitors:
        if comp.flag == "cannot_articulate_difference" or comp.why_we_are_not_them is None:
            wedge = Text("(cannot articulate difference)", style="dim italic")
        else:
            wedge = Text(comp.why_we_are_not_them)
        t.add_row(comp.name, comp.what_they_do, wedge)
    return Group(
        Text("▸ Landscape", style="bold cyan"),
        Text(""),
        Padding(t, (0, 0, 1, 2)),
    )


_NO_DISSENT_TEXT = (
    "No dissent survived this debate. Either consensus was real, or the\n"
    "orchestration is collapsing voices — flag for ai-ml-engineer review."
)


def _dissent_block(d: Dissent) -> Group:
    quote = Text(f'┃ "{d.verbatim}"', style="yellow")
    attr = Text(f"┃    — {_voice_display(d.voice)}", style="dim")
    return Group(quote, attr, Text(""))


def _dissent_section(dissent: SurvivingDissent | None) -> Group:
    header = Text.assemble(
        ("▸ Surviving Dissent", "bold cyan"),
        ("                                                          [!]", "yellow"),
    )
    if dissent is None or dissent.dissent_status == "no_surviving_dissent" or not dissent.dissents:
        body = Text(_NO_DISSENT_TEXT, style="yellow")
        return Group(header, Text(""), Padding(body, (0, 0, 1, 2)))
    blocks: list[Group] = [_dissent_block(d) for d in dissent.dissents]
    return Group(header, Text(""), Padding(Group(*blocks), (0, 0, 1, 2)))


def _next_step_block(i: int, step: NextStep) -> Group:
    return Group(
        Text.assemble((f"  {i}. ", "bold"), step.action),
        Text.assemble(("     Surfaced by: ", "dim"), _voice_display(step.surfaced_by_voice)),
        Text.assemble(
            ("     Falsifier:   ", "dim yellow"),
            f"{step.falsifier.what_would_disprove_this} ({step.falsifier.by_when})",
        ),
    )


def _next_steps_section(next_steps: NextStepsWithFalsifiers) -> Group:
    items: list[Group | Text | Padding] = [Text("▸ Next Steps", style="bold cyan"), Text("")]
    if not next_steps.steps:
        items.append(
            Padding(Text("(no next steps surfaced for this verdict)", style="dim"), (0, 0, 1, 2))
        )
        return Group(*items)
    for i, step in enumerate(next_steps.steps[:5], start=1):
        items.append(Padding(_next_step_block(i, step), (0, 0, 1, 0)))
    return Group(*items)


def _verdict_url_line(result: ResearchResult) -> str:
    """PD-spec footer: name what's behind the paywall door.

    Composes a single line of *real* counts from the post-processor
    readouts (turns, surviving dissents, dated falsifiers) plus the fixed
    $2.50 price and the verdict URL. Each clause is only included when the
    underlying number is genuinely available — we never fabricate counts.
    Falls back to the legacy ``Full transcript: x402://verdict/<hash>
    (paywalled)`` line when no counts are reachable.
    """
    short = _short_hash(result)
    clauses: list[str] = []

    # Turn count: pull from the weakly-typed transcript dict if present.
    turn_count: int | None = None
    if isinstance(result.transcript, dict):
        turns = result.transcript.get("turns")
        if isinstance(turns, list):
            turn_count = len(turns)
    if turn_count:
        clauses.append(f"{turn_count} turn{'s' if turn_count != 1 else ''}")

    # Surviving dissents: only count when the status is "surviving" — a
    # collapsed/empty list isn't a real count, it's the absence of one.
    dissent_count: int | None = None
    sd = result.surviving_dissent
    if sd is not None and sd.dissent_status == "surviving":
        dissent_count = len(sd.dissents)
    if dissent_count:
        clauses.append(f"{dissent_count} surviving dissent{'s' if dissent_count != 1 else ''}")

    # Dated falsifiers: each NextStep carries one, so the count is the
    # length of the steps list when present.
    step_count: int | None = None
    if result.next_steps_with_falsifiers is not None:
        step_count = len(result.next_steps_with_falsifiers.steps)
    if step_count:
        clauses.append(f"{step_count} dated falsifier{'s' if step_count != 1 else ''}")

    if not clauses:
        return f"  Full transcript: x402://verdict/{short} (paywalled)"

    body = " · ".join(["Full debate", *clauses, "$2.50"])
    return f"  {body} — x402://verdict/{short}"


def _calibration_footer_line(result: ResearchResult) -> Text | None:
    """Render the calibration footer line when the run was calibrated.

    Format mirrors the spec: ``Calibrated against 34 Colosseum judges
    across 14 regions · 2026-05-03 corpus``. Returns ``None`` when the
    result was not calibrated so the caller can skip the line cleanly.
    """
    cid = getattr(result, "calibration_corpus", None)
    if not cid:
        return None
    # Identifier shapes:
    #   colosseum:<N>_judges:<YYYY-MM-DD>                       (Colosseum only)
    #   colosseum:<N>_judges:<M>_programs:<YYYY-MM-DD>          (+ web3 accelerators)
    parts = cid.split(":")
    if len(parts) >= 3 and parts[0] == "colosseum":
        try:
            n_judges = int(parts[1].split("_")[0])
        except (ValueError, IndexError):
            n_judges = 0

        # Parse optional programs segment + trailing date.
        n_programs = 0
        date_part = parts[-1]
        for seg in parts[2:-1]:
            if seg.endswith("_programs"):
                try:
                    n_programs = int(seg.split("_")[0])
                except (ValueError, IndexError):
                    n_programs = 0

        # Region count is hard-coded against the 2026-05-03 dataset (14
        # superteam regions in the source file). The judge / program
        # counts come from the loaded chunks, so adding new programs
        # widens the footer automatically.
        n_regions = 14
        if n_judges > 0 and n_programs > 0:
            return Text(
                f"  Calibrated against {n_judges} Colosseum judges + "
                f"{n_programs} web3 accelerator programs · {date_part} corpus",
                style="dim",
            )
        if n_judges > 0:
            return Text(
                f"  Calibrated against {n_judges} Colosseum judges "
                f"across {n_regions} regions · {date_part} corpus",
                style="dim",
            )
    return Text(f"  Calibrated against {cid}", style="dim")


def _footer_section(result: ResearchResult) -> Group:
    short = _short_hash(result)
    items: list[Text | Rule] = [
        Rule(style="dim"),
        Text(f"  {result.tier} · verdict@{short}", style="dim"),
        Text(_verdict_url_line(result), style="dim"),
    ]
    cal_line = _calibration_footer_line(result)
    if cal_line is not None:
        items.append(cal_line)
    items.append(
        Text(
            f"  Next: gecko_advise --hash {short}  to debate this verdict further.",
            style="dim",
        )
    )
    return Group(*items)


def render_research_demo(
    result: ResearchResult,
    idea: str,
    console: Console | None = None,
) -> None:
    """Render the v5.5 demo output: 7 sections, verdict-led.

    Sections degrade gracefully when post-processor fields are None — except
    Surviving Dissent, which always renders (with a self-incrimination line
    when missing) per design spec §2.5.
    """
    c = _console(console)
    c.print(_demo_header(result, idea))
    if result.per_voice is not None:
        c.print(_voices_section(result.per_voice))
    if result.transcript_summary:
        c.print(_transcript_section(result.transcript_summary))
    if result.market_landscape is not None and result.market_landscape.competitors:
        c.print(_landscape_section(result.market_landscape))
    c.print(_dissent_section(result.surviving_dissent))
    if result.next_steps_with_falsifiers is not None:
        c.print(_next_steps_section(result.next_steps_with_falsifiers))
    c.print(_footer_section(result))


def render_research_result(result: ResearchResult, console: Console | None = None) -> None:
    """Render the three documents as the reveal moment."""
    c = _console(console)

    # Long ideas / long session ids: fold gracefully.
    header = Text(overflow="fold", no_wrap=False)
    header.append("Session ", style=_HEADER_STYLE)
    header.append(result.session_id, style="bold")
    header.append("   tier ", style=_HEADER_STYLE)
    header.append(result.tier, style="bold")
    header.append(f"   {len(result.sources)} sources", style=_HEADER_STYLE)

    c.print(Padding(header, (0, 0, 1, 0)))

    c.print(
        _doc_panel(
            "Business Plan",
            _business_plan_body(result.business_plan, _BP_STYLE),
            _BP_STYLE,
        )
    )

    c.print(Rule(Text("Validation", style=f"bold {_VR_STYLE}"), style=_VR_STYLE))

    c.print(
        _doc_panel(
            "Validation Report",
            _validation_body(result.validation_report, _VR_STYLE, verdict=result.verdict),
            _VR_STYLE,
        )
    )

    c.print(Rule(Text("PRD", style=f"bold {_PRD_STYLE}"), style=_PRD_STYLE))

    c.print(
        _doc_panel(
            "PRD",
            _prd_body(
                result.prd,
                _PRD_STYLE,
                gap=result.validation_report,
                verdict=result.verdict,
            ),
            _PRD_STYLE,
        )
    )


# --- Sources table ---------------------------------------------------------


def _relative_time(when: datetime, *, now: datetime | None = None) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    n = now or datetime.now(UTC)
    if n.tzinfo is None:
        n = n.replace(tzinfo=UTC)
    delta = n - when
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86_400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86_400}d ago"


def render_sources_table(sources: list[SourceInfo], console: Console | None = None) -> None:
    c = _console(console)
    table = Table(
        title=Text(f"Indexed sources ({len(sources)})", style="bold"),
        title_justify="left",
        box=ROUNDED,
        expand=True,
        show_lines=False,
    )
    table.add_column("#", justify="right", style=_META_STYLE, no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Chunks", justify="right", no_wrap=True)
    table.add_column("Indexed", style=_META_STYLE, no_wrap=True)
    table.add_column("URL", overflow="fold")

    if not sources:
        table.add_row("-", "-", "-", "-", Text("(no sources indexed yet)", style=_META_STYLE))
        c.print(table)
        return

    ordered = sorted(sources, key=lambda s: s.indexed_at, reverse=True)
    for i, s in enumerate(ordered, start=1):
        url = str(s.url)
        url_text = Text(url, style=f"link {url}")
        table.add_row(
            str(i),
            s.type,
            str(s.chunk_count),
            _relative_time(s.indexed_at),
            url_text,
        )
    c.print(table)


# --- Ask result ------------------------------------------------------------


def render_ask_result(result: AskResult, console: Console | None = None) -> None:
    c = _console(console)
    accent = "cyan"
    parts: list[Text | Group] = [Text(result.answer)]
    cites = _citations_renderable(result.citations, accent)
    if cites is not None:
        parts.append(_spacer())
        parts.append(cites)
    body = Group(*parts)
    c.print(
        Panel(
            body,
            title=Text("Answer", style=f"bold {accent}"),
            title_align="left",
            border_style=accent,
            box=ROUNDED,
            padding=(1, 2),
            expand=True,
        )
    )


# --- Source candidates (approval flow) -------------------------------------


def render_source_candidates(
    candidates: list[SourceCandidate], console: Console | None = None
) -> None:
    c = _console(console)
    table = Table(
        title=Text(f"Discovered sources ({len(candidates)})", style="bold"),
        title_justify="left",
        box=ROUNDED,
        expand=True,
    )
    table.add_column("#", justify="right", style=_META_STYLE, no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Title", overflow="fold")
    table.add_column("URL", overflow="fold")

    if not candidates:
        table.add_row("-", "-", Text("(none)", style=_META_STYLE), "-")
        c.print(table)
        return

    for i, cand in enumerate(candidates, start=1):
        url = str(cand.url)
        title_cell: Text = Text(cand.title) if cand.title else Text("(no title)", style=_META_STYLE)
        table.add_row(
            str(i),
            cand.type,
            title_cell,
            Text(url, style=f"link {url}"),
        )
    c.print(table)


# --- Progress --------------------------------------------------------------


def _build_progress(console: Console | None) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=None),
        TextColumn("[dim]{task.fields[phase]}"),
        TimeElapsedColumn(),
        console=_console(console),
        transient=False,
        expand=True,
    )


@contextmanager
def progress_context(console: Console | None = None) -> Iterator[Progress]:
    """Context manager yielding a configured `rich.progress.Progress`.

    Workflow phases the caller will advance through: discovery -> indexing ->
    generating -> complete. Use `WorkflowProgress` for the canonical phase
    sequence on a single task; this raw context is for callers that want full
    control.
    """
    progress = _build_progress(console)
    with progress:
        yield progress


class WorkflowProgress:
    """Single-task progress helper with the canonical workflow phases.

    Usage:
        with WorkflowProgress(console) as wp:
            wp.start_discovery()
            ...
            wp.start_indexing(7)
            ...
            wp.start_generating()
            ...
            wp.complete()
    """

    def __init__(self, console: Console | None = None) -> None:
        self._progress = _build_progress(console)
        self._task_id: TaskID | None = None

    def __enter__(self) -> WorkflowProgress:
        self._progress.__enter__()
        self._task_id = self._progress.add_task("Starting", total=None, phase="initializing")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._progress.__exit__(exc_type, exc, tb)

    def _update(self, description: str, phase: str, total: float | None = None) -> None:
        if self._task_id is None:
            return
        self._progress.update(self._task_id, description=description, phase=phase, total=total)

    def start_discovery(self) -> None:
        self._update("Discovering sources", phase="discovery")

    def start_indexing(self, n: int) -> None:
        self._update(f"Indexing {n} sources", phase=f"indexing ({n})", total=float(n))

    def advance_indexing(self, step: float = 1.0) -> None:
        if self._task_id is None:
            return
        self._progress.advance(self._task_id, step)

    def start_generating(self) -> None:
        self._update("Generating documents", phase="generation", total=None)

    def complete(self) -> None:
        if self._task_id is None:
            return
        self._progress.update(self._task_id, description="Complete", phase="done")
        self._progress.stop_task(self._task_id)


# --- Pulse renderer (S14-PULSE-03) -----------------------------------------
#
# Pulse panel mirrors the Validation panel style — same yellow accent (the
# pulse is an act of scrutiny against fresh evidence), same verdict + gap
# headline. v14 is intentionally text-only: no delta diff against the
# parent session yet (that's S15-PULSE-DELTA-01). The panel surfaces:
#   * single-token verdict + gap_classification
#   * 3-bullet "what the panel said this time" summary
#   * fresh windowed citations (last 14 days)
#   * the parent session_id in the footer for traceability


_PULSE_STYLE = _VR_STYLE


def render_pulse_result(result: object, console: Console | None = None) -> None:
    """S14-PULSE-03 — render a PulseResult as a single Validation-styled panel.

    Accepts the PulseResult model declared in
    ``gecko_core.orchestration.advisor.models``; we type the parameter as
    ``object`` here to avoid importing a sibling-package model at module
    load (matches the rest of render.py's lightweight-import discipline).
    """
    from gecko_core.orchestration.advisor.models import PulseResult as _PR

    if not isinstance(result, _PR):
        raise TypeError("render_pulse_result expects a PulseResult instance")

    c = _console(console)

    header = Text(overflow="fold", no_wrap=False)
    header.append("Pulse for: ", style=_HEADER_STYLE)
    header.append(result.idea, style="bold")
    c.print(Padding(header, (0, 0, 1, 0)))

    parts: list[Text | Group] = [
        _verdict_line(result.verdict),
        _spacer(),
    ]

    gap_line = Text()
    gap_line.append("Gap: ", style=f"bold {_PULSE_STYLE}")
    gap_line.append(result.gap_classification, style="bold")
    parts.append(gap_line)
    parts.append(_spacer())

    if result.summary_bullets:
        parts.append(_bullets("What the panel said", result.summary_bullets, _PULSE_STYLE))
        parts.append(_spacer())

    cites = _citations_renderable(result.citations, _PULSE_STYLE)
    if cites is not None:
        parts.append(cites)
        parts.append(_spacer())

    footer = Text()
    footer.append("parent session: ", style=_META_STYLE)
    footer.append(result.parent_session_id, style="dim")
    footer.append("   pulse session: ", style=_META_STYLE)
    footer.append(result.pulse_session_id, style="dim")
    if result.credits_remaining_after is not None:
        footer.append("   credits left: ", style=_META_STYLE)
        footer.append(str(result.credits_remaining_after), style="dim")
    parts.append(footer)

    body = Group(*parts)
    c.print(_doc_panel("Pulse", body, _PULSE_STYLE))


# --- Refine -----------------------------------------------------------------


def _render_refine(
    refinement: RefinedIdea,
    *,
    short_hash: str,
    console: Console | None = None,
) -> None:
    """Render a `bb refine <hash>` output panel.

    Layout follows the spec:
      - top panel: verdict@<hash> · refinement: <kind>
      - body sections: addresses-dissent, now-claims, falsifiers
      - footer: $1.00 V1.5 paywall + next CTA
    """
    c = _console(console)

    # Top panel: identifier + refinement kind. Padded with the refined
    # statement as the lead body so the founder sees the headline first.
    header = Text.assemble(
        ("verdict@", "dim"),
        (short_hash, "bold"),
        ("  ·  refinement: ", "dim"),
        (refinement.confidence, "bold cyan"),
    )
    statement = Text.assemble(
        ("Refined statement: ", "bold"),
        Text(refinement.refined_statement, no_wrap=False),
    )
    c.print(
        Panel(
            Group(header, Text(""), statement),
            title=Text("Idea Refinement", style="bold cyan"),
            border_style="cyan",
            box=ROUNDED,
            padding=(1, 2),
            expand=True,
        )
    )

    # Section 1 — surviving dissent addressed.
    if refinement.addresses_dissent:
        c.print()
        c.print(Text("▸ Addresses surviving dissent", style="bold cyan"))
        c.print()
        for d in refinement.addresses_dissent:
            voice = _voice_display(d.voice)
            quote = Text.assemble(
                ("  ▸ ", "dim"),
                (f"{voice}: ", "bold"),
                (f'"{d.dissent_quote}"', "yellow"),
            )
            res = Text.assemble(
                ("    Resolution: ", "dim"),
                Text(d.resolution),
            )
            c.print(quote)
            c.print(res)
            c.print()

    # Section 2 — now-claims (paired was → now).
    pairs = list(
        zip(
            refinement.what_it_no_longer_claims,
            refinement.what_it_now_claims_instead,
            strict=False,
        )
    )
    if pairs:
        c.print(Text("▸ Now claims (was)", style="bold cyan"))
        c.print()
        for was, now in pairs:
            line = Text.assemble(
                ("  - was ", "dim"),
                Text(was),
                ("    →    now ", "dim"),
                Text(now, style="bold"),
            )
            c.print(line)
        c.print()

    # Section 3 — falsifiers no longer easy.
    if refinement.new_falsifiers_now_harder:
        c.print(Text("▸ Falsifiers no longer easy", style="bold cyan"))
        c.print()
        for f in refinement.new_falsifiers_now_harder:
            c.print(Text.assemble(("  - ", "dim"), Text(f)))
        c.print()

    # Footer.
    c.print(Rule(style="dim"))
    c.print(
        Text(
            f"  Refined from verdict@{short_hash}  ·  $1.00 per refinement (V1.5 paywall)",
            style="dim",
        )
    )
    c.print(
        Text(
            f"  Next: gecko_advise --hash {short_hash}  to debate this refinement.",
            style="dim",
        )
    )


__all__ = [
    "WorkflowProgress",
    "_render_refine",
    "progress_context",
    "render_ask_result",
    "render_pulse_result",
    "render_research_demo",
    "render_research_result",
    "render_source_candidates",
    "render_sources_table",
]
