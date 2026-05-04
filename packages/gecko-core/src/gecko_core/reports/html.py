"""Pure-function HTML report renderer for Gecko research sessions.

S23-REPORT-01.

`render_html_report` produces a self-contained HTML document from a
``ResearchResult`` (and optionally an ``AdvisorPanel`` and a list of
``AskResult``s). Zero network calls — the function is synchronous and
has no external dependencies beyond the stdlib and the models it imports.

CSS token names match the hand-built demo at
``/tmp/gecko-demo/gecko-e2e-2026-05-04.html`` so the rendered output is
visually consistent with the reference.

Design decisions:
- f-strings + helper functions instead of Jinja to avoid a template
  engine dependency.
- All honest-failure rules enforced: gap_explanation=None shows a
  callout; surviving_dissent=None omits that section; plan=None omits
  the panel section.
- No synthesis from gap_summary when gap_explanation is absent.

<!-- TODO S24: embedding-based disagreement detection -->
"""

from __future__ import annotations

import html as _html
import importlib.metadata
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from gecko_core.models import AskResult, ResearchResult, Verdict

if TYPE_CHECKING:
    from gecko_core.orchestration.advisor.models import AdvisorPanel


# ---------------------------------------------------------------------------
# CSS (inline, no external deps — CSS tokens match the demo)
# ---------------------------------------------------------------------------

_CSS = """
:root {
  --bg: #0e1116;
  --panel: #161b22;
  --panel-2: #1f242c;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --accent-2: #7ee787;
  --warn: #f0883e;
  --bad: #f85149;
  --good: #56d364;
  --refine: #d29922;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55;
}
.container { max-width: 1080px; margin: 0 auto; padding: 32px 24px 80px; }
header { border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 32px; }
h1 { font-size: 28px; margin: 0 0 8px; letter-spacing: -0.02em; }
h1 .gecko { color: var(--accent-2); }
h2 { font-size: 19px; margin: 40px 0 14px; padding-bottom: 8px; border-bottom: 1px solid var(--border); letter-spacing: -0.01em; }
h3 { font-size: 15px; margin: 22px 0 10px; color: var(--text); }
p { margin: 0 0 12px; }
.muted { color: var(--muted); font-size: 13px; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
code { background: var(--panel-2); padding: 1px 5px; border-radius: 3px; color: var(--accent-2); }
pre { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; overflow-x: auto; line-height: 1.5; }
.meta-row { display: flex; flex-wrap: wrap; gap: 12px 24px; margin-bottom: 4px; }
.meta-row > div { font-size: 13px; }
.meta-label { color: var(--muted); margin-right: 6px; }
.badge { display: inline-block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); margin-right: 6px; vertical-align: middle; }
.badge.refine { background: rgba(210, 153, 34, 0.12); color: var(--refine); border-color: var(--refine); }
.badge.go { background: rgba(86, 211, 100, 0.10); color: var(--good); border-color: var(--good); }
.badge.pivot { background: rgba(248, 81, 73, 0.10); color: var(--bad); border-color: var(--bad); }
.badge.kill { background: rgba(248, 81, 73, 0.15); color: var(--bad); border-color: var(--bad); }
.badge.warn { background: rgba(240, 136, 62, 0.10); color: var(--warn); border-color: var(--warn); }
.badge.good { background: rgba(86, 211, 100, 0.10); color: var(--good); border-color: var(--good); }
.badge.bad { background: rgba(248, 81, 73, 0.10); color: var(--bad); border-color: var(--bad); }
.badge.muted { color: var(--muted); }
ul { padding-left: 20px; }
li { margin: 4px 0; }
table { width: 100%; border-collapse: collapse; font-size: 13.5px; margin: 8px 0; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 500; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; background: var(--panel-2); }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
table.kv th { width: 200px; color: var(--accent); background: transparent; text-transform: none; letter-spacing: normal; font-size: 13px; font-weight: 500; }
table.kv td { color: var(--text); }
.voice { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 18px 22px; margin-bottom: 18px; }
.voice h3 { display: flex; align-items: center; gap: 10px; margin-top: 0; font-size: 16px; }
.voice-role { text-transform: uppercase; letter-spacing: 0.08em; font-size: 11px; color: var(--accent); background: rgba(88, 166, 255, 0.10); padding: 2px 8px; border-radius: 4px; border: 1px solid rgba(88, 166, 255, 0.25); }
.voice-meta { color: var(--muted); font-size: 12px; margin-left: auto; }
.voice-body { font-size: 14px; line-height: 1.62; color: var(--text); }
.closing { margin-top: 12px; padding-top: 12px; border-top: 1px dashed var(--border); font-size: 13px; color: var(--accent-2); }
.closing::before { content: "\\25b8 "; color: var(--muted); }
.qa { margin-bottom: 20px; }
.qa-q { color: var(--accent); font-weight: 500; margin-bottom: 4px; font-size: 14px; }
.qa-a { color: var(--text); background: var(--panel-2); border-left: 3px solid var(--border); padding: 10px 14px; border-radius: 4px; font-size: 13.5px; line-height: 1.55; }
.source-link { color: var(--accent); text-decoration: none; word-break: break-all; }
.source-link:hover { text-decoration: underline; }
.footer { margin-top: 60px; padding-top: 24px; border-top: 1px solid var(--border); color: var(--muted); font-size: 12.5px; }
.conflict { background: rgba(240, 136, 62, 0.08); border: 1px solid rgba(240, 136, 62, 0.4); color: var(--text); padding: 14px 18px; border-radius: 6px; font-size: 13.5px; margin: 18px 0; }
.conflict strong { color: var(--warn); }
.info-note { background: rgba(88, 166, 255, 0.08); border: 1px solid rgba(88, 166, 255, 0.4); padding: 12px 16px; border-radius: 6px; font-size: 13px; margin: 14px 0; }
.info-note strong { color: var(--accent); }
details summary { cursor: pointer; font-size: 12.5px; color: var(--accent); user-select: none; padding: 4px 0; }
details summary:hover { color: var(--accent-2); }
details[open] summary { color: var(--muted); margin-bottom: 8px; }
.panel-failed-banner { background: rgba(248, 81, 73, 0.08); border: 1px solid rgba(248, 81, 73, 0.4); color: var(--text); padding: 12px 16px; border-radius: 6px; font-size: 13px; margin: 14px 0; }
.panel-failed-banner strong { color: var(--bad); }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _e(text: str) -> str:
    """HTML-escape a string."""
    return _html.escape(str(text or ""))


def _verdict_badge(verdict: Verdict | str) -> str:
    v = str(verdict).upper()
    css_class = {
        "GO": "go",
        "REFINE": "refine",
        "PIVOT": "pivot",
        "KILL": "kill",
    }.get(v, "muted")
    return f'<span class="badge {css_class}">{_e(v)}</span>'


def _items_as_ul(items: list[str]) -> str:
    if not items:
        return "<em class='muted'>—</em>"
    lis = "".join(f"<li>{_e(item)}</li>" for item in items)
    return f'<ul style="margin: 0;">{lis}</ul>'


def _kv_row(label: str, value_html: str) -> str:
    return f"<tr><th>{_e(label)}</th><td>{value_html}</td></tr>"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_header(result: ResearchResult) -> str:
    verdict_badge = _verdict_badge(result.verdict)
    session_id = _e(result.session_id)
    tier = _e(result.tier)
    hash_val = _e(result.verdict_hash or "—")
    low_grounding_badge = (
        '<span class="badge warn">low_grounding</span>' if result.low_grounding else ""
    )
    provider_mix_badge = (
        f'<span class="badge warn">{_e(str(result.provider_mix_flag))}</span>'
        if result.provider_mix_flag
        else ""
    )
    return f"""
<header>
  <h1><span class="gecko">Gecko</span> — Research Report</h1>
  <div class="meta-row">
    <div><span class="meta-label">Session</span><code>{session_id}</code></div>
    <div><span class="meta-label">Tier</span><code>{tier}</code></div>
    <div><span class="meta-label">Verdict</span>{verdict_badge}</div>
    <div><span class="meta-label">Hash</span><code>{hash_val}</code></div>
    {f"<div>{low_grounding_badge}</div>" if low_grounding_badge else ""}
    {f"<div>{provider_mix_badge}</div>" if provider_mix_badge else ""}
  </div>
</header>
"""


def _render_sources(result: ResearchResult) -> str:
    if not result.sources:
        return ""
    rows = "".join(
        f"<tr>"
        f'<td><a class="source-link" href="{_e(s.url)}">{_e(s.url)}</a></td>'
        f'<td class="num"><code>{s.chunk_count}</code></td>'
        f"</tr>"
        for s in result.sources
    )
    return f"""
<h2>Sources</h2>
<table>
  <thead><tr><th>URL</th><th class="num">Chunks</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""


def _render_validation(result: ResearchResult) -> str:
    vr = result.validation_report
    risk_flags_html = _items_as_ul(vr.risk_flags)
    low_note: str
    rows = f"""
  {_kv_row("gap_classification", f"<code>{_e(vr.gap_classification)}</code>")}
  {_kv_row("gap_summary", _e(vr.gap_summary))}
  {_kv_row("demand_evidence", _e(vr.demand_evidence))}
  {_kv_row("risk_flags", risk_flags_html)}
  {_kv_row("market_size_signal", _e(vr.market_size_signal))}
  {_kv_row("competitor_analysis", _e(vr.competitor_analysis))}
"""

    if result.low_explanation or not vr.gap_explanation:
        # Honest failure: show callout, do NOT synthesize from gap_summary.
        low_note = (
            '<div class="conflict">'
            "<strong>Note:</strong> The model did not produce an explanation for this verdict. "
            "Treat the verdict letter and gap_summary alone."
            "</div>"
        )
    else:
        rows += _kv_row("gap_explanation", _e(vr.gap_explanation))
        low_note = ""

    return f"""
<h2>Validation</h2>
{low_note}
<table class="kv">
  {rows}
</table>
"""


def _render_business_plan(result: ResearchResult) -> str:
    bp = result.business_plan
    rows = f"""
  {_kv_row("problem", _e(bp.problem))}
  {_kv_row("ICP", _e(bp.icp))}
  {_kv_row("solution", _e(bp.solution))}
  {_kv_row("market", _e(bp.market))}
  {_kv_row("channels", _e(bp.channels))}
  {_kv_row("business_model", _e(bp.business_model))}
  {_kv_row("risks", _items_as_ul(bp.risks))}
"""
    return f"""
<h2>Business Plan</h2>
<table class="kv">
  {rows}
</table>
"""


def _render_prd(result: ResearchResult) -> str:
    prd = result.prd

    def _scope_row(label: str, items: list[str]) -> str:
        return f"<tr><td><strong>{_e(label)}</strong></td><td>{_items_as_ul(items)}</td></tr>"

    rows = (
        _scope_row("v1_scope", prd.v1_scope)
        + _scope_row("v2_scope", prd.v2_scope)
        + _scope_row("v3_scope", prd.v3_scope)
        + _scope_row("acceptance_criteria", prd.acceptance_criteria)
        + _scope_row("non_functional", prd.non_functional)
        + _scope_row("success_metrics", prd.success_metrics)
    )
    return f"""
<h2>PRD</h2>
<table>
  <thead><tr><th>Scope</th><th>Items</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""


def _render_asks(asks: list[AskResult]) -> str:
    if not asks:
        return ""
    items: list[str] = []
    for ask in asks:
        citation_count = len(ask.citations)
        items.append(
            f'<div class="qa">'
            f'<div class="qa-q">Q. {_e(ask.answer[:200])}</div>'
            f'<div class="qa-a">{_e(ask.answer)}</div>'
            f'<div class="muted">{citation_count} citation(s)</div>'
            f"</div>"
        )
    return f"""
<h2>Q&amp;A</h2>
{"".join(items)}
"""


def _render_panel(plan: AdvisorPanel) -> str:
    """Render the 5-voice advisor panel.

    Honest-failure rules:
    - voices_failed_no_content > 0 → show banner
    - output_md goes in <details>, not inline
    """
    failed_banner = ""
    if plan.voices_failed_no_content > 0:
        failed_banner = (
            '<div class="panel-failed-banner">'
            f"<strong>{plan.voices_failed_no_content} of 5 voice(s) failed</strong>"
            " (provider returned no content)."
            "</div>"
        )

    # Summary table
    summary_rows = ""
    for voice in plan.voices:
        role_name = str(voice.role.value if hasattr(voice.role, "value") else voice.role)
        cost_str = f"${voice.cost_usd:.4f}" if voice.cost_usd is not None else "—"
        summary_rows += (
            f"<tr>"
            f"<td><span class='voice-role'>{_e(role_name)}</span></td>"
            f"<td><code>{_e(voice.model_used)}</code></td>"
            f"<td class='num'>{_e(cost_str)}</td>"
            f"<td>{_e(voice.closing_line)}</td>"
            f"</tr>"
        )

    summary_table = f"""
<table>
  <thead>
    <tr>
      <th>Role</th>
      <th>Model</th>
      <th class="num">Cost</th>
      <th>Closing line</th>
    </tr>
  </thead>
  <tbody>{summary_rows}</tbody>
</table>
"""

    # Per-voice detail blocks
    detail_blocks = ""
    for voice in plan.voices:
        role_name = str(voice.role.value if hasattr(voice.role, "value") else voice.role)
        escaped_md = _e(voice.output_md or "")
        detail_blocks += f"""
<div class="voice">
  <h3>
    <span class="voice-role">{_e(role_name)}</span>
    <span class="voice-meta">{_e(voice.model_used)}</span>
  </h3>
  <details>
    <summary>Show full output</summary>
    <pre style="white-space: pre-wrap; word-break: break-word; max-height: 500px; overflow-y: auto;">{escaped_md}</pre>
  </details>
  <div class="closing">{_e(voice.closing_line)}</div>
</div>
"""

    return f"""
<h2>5-Voice Advisor Panel</h2>
{failed_banner}
{summary_table}
{detail_blocks}
"""


def _render_economics(result: ResearchResult) -> str:
    """Render run economics section."""
    hash_val = result.verdict_hash or "—"
    provider_mix = str(result.provider_mix_flag) if result.provider_mix_flag else "—"
    return f"""
<h2>Run Economics</h2>
<table class="kv">
  {_kv_row("verdict_hash", f"<code>{_e(hash_val)}</code>")}
  {_kv_row("provider_mix_flag", f"<code>{_e(provider_mix)}</code>")}
  {_kv_row("tier", _e(result.tier))}
</table>
"""


def _render_footer(version: str, timestamp: str) -> str:
    return f"""
<div class="footer">
  Generated by Gecko v{_e(version)} &middot; {_e(timestamp)}
</div>
"""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_html_report(
    result: ResearchResult,
    plan: AdvisorPanel | None = None,
    asks: list[AskResult] | None = None,
) -> str:
    """Render a self-contained HTML report for a completed research session.

    Pure function — no network calls, no side effects. Safe to call from
    any sync context.

    Args:
        result: The persisted ResearchResult for the session.
        plan:   Optional AdvisorPanel (from gecko_plan). When None, the
                5-voice panel section is omitted.
        asks:   Optional list of AskResult objects. When None or empty,
                the Q&A section is omitted.

    Returns:
        A complete HTML document as a string.
    """
    try:
        version = importlib.metadata.version("gecko-core")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    sections: list[str] = [
        _render_header(result),
        _render_sources(result),
        _render_validation(result),
        _render_business_plan(result),
        _render_prd(result),
    ]

    if asks:
        sections.append(_render_asks(asks))

    if plan is not None:
        sections.append(_render_panel(plan))

    # surviving_dissent section — omit entirely when None
    if result.surviving_dissent is not None:
        sd = result.surviving_dissent
        dissent_items = "".join(
            f"<li><strong>{_e(str(d.voice))}</strong>: {_e(d.verbatim)}</li>" for d in sd.dissents
        )
        sections.append(
            f"<h2>Surviving Dissent</h2>"
            f'<p class="muted">{_e(sd.dissent_status)}</p>'
            f'<ul style="margin: 0;">{dissent_items}</ul>'
            f"<p>{_e(sd.rationale)}</p>"
        )

    sections.append(_render_economics(result))
    sections.append(_render_footer(version, timestamp))

    body = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Gecko Report — {_e(result.session_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="container">
{body}
</div>
</body>
</html>"""


def render_markdown_report(
    result: ResearchResult,
    plan: AdvisorPanel | None = None,
    asks: list[AskResult] | None = None,
) -> str:
    """Render a markdown report. Thin wrapper that builds the key sections.

    Returns plain markdown text (not HTML).
    """
    lines: list[str] = []
    lines.append(f"# Gecko Report — {result.session_id}")
    lines.append("")
    lines.append(f"**Verdict:** {result.verdict}")
    lines.append(f"**Tier:** {result.tier}")
    lines.append(f"**Hash:** {result.verdict_hash or '—'}")
    lines.append("")

    vr = result.validation_report
    lines.append("## Validation")
    lines.append(f"- **gap_classification:** {vr.gap_classification}")
    lines.append(f"- **gap_summary:** {vr.gap_summary}")
    if result.low_explanation or not vr.gap_explanation:
        lines.append("_Note: The model did not produce an explanation for this verdict._")
    else:
        lines.append(f"- **gap_explanation:** {vr.gap_explanation}")
    lines.append("")

    bp = result.business_plan
    lines.append("## Business Plan")
    lines.append(f"- **Problem:** {bp.problem}")
    lines.append(f"- **Solution:** {bp.solution}")
    lines.append(f"- **ICP:** {bp.icp}")
    lines.append(f"- **Market:** {bp.market}")
    lines.append("")

    prd = result.prd
    lines.append("## PRD")
    lines.append("**V1 scope:**")
    for item in prd.v1_scope:
        lines.append(f"- {item}")
    lines.append("")

    if asks:
        lines.append("## Q&A")
        for ask in asks:
            lines.append(f"**A:** {ask.answer}")
            lines.append(f"_Citations: {len(ask.citations)}_")
            lines.append("")

    if plan is not None:
        lines.append("## 5-Voice Advisor Panel")
        if plan.voices_failed_no_content > 0:
            lines.append(
                f"**{plan.voices_failed_no_content} of 5 voice(s) failed** "
                "(provider returned no content)."
            )
        for voice in plan.voices:
            role_name = str(voice.role.value if hasattr(voice.role, "value") else voice.role)
            lines.append(f"### {role_name} ({voice.model_used})")
            lines.append(f"_{voice.closing_line}_")
            lines.append("")

    return "\n".join(lines)


__all__ = ["render_html_report", "render_markdown_report"]
