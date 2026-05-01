"""S13-CITE-01 — citation creator-attribution rendering tests.

Validates that:
  1. Citations with all three creator fields populated render the inline
     handle/payout/wallet sub-line and a "Creator payouts" footer.
  2. Citations with all creator fields ``None`` render byte-identically to
     pre-S13 (no sub-line, no footer) — pre-Paragraph runs are unaffected.
"""

from __future__ import annotations

import io

from gecko_cli.render import (
    _citations_renderable,
    _creator_payouts_footer,
    _truncate_wallet,
)
from gecko_core.models import Citation
from rich.console import Console


def _cite(
    url: str = "https://paragraph.xyz/@author/post-slug",
    *,
    handle: str | None = None,
    payout: float | None = None,
    wallet: str | None = None,
) -> Citation:
    return Citation(
        source_url=url,  # type: ignore[arg-type]
        chunk_index=4,
        similarity=0.82,
        creator_handle=handle,
        creator_payout_usd=payout,
        creator_wallet=wallet,
    )


def _render(renderable: object) -> str:
    buf = io.StringIO()
    Console(file=buf, width=120, force_terminal=False, no_color=True).print(renderable)
    return buf.getvalue()


# --- Inline rendering ------------------------------------------------------


def test_citation_with_all_creator_fields_renders_inline_handle() -> None:
    cites = [
        _cite(
            handle="author",
            payout=0.0050,
            wallet="7xKXabcdefghijklmnop9Lm",
        )
    ]
    out = _render(_citations_renderable(cites, accent="cyan"))
    assert "@author" in out
    assert "$0.0050 paid" in out
    # Truncated wallet (4+4 with ellipsis).
    assert "7xKX…p9Lm" in out
    # Full wallet must NOT leak.
    assert "7xKXabcdefghijklmnop9Lm" not in out


def test_citation_with_only_handle_renders_handle_only() -> None:
    cites = [_cite(handle="alice")]
    out = _render(_citations_renderable(cites, accent="cyan"))
    assert "@alice" in out
    assert "paid" not in out


# --- Footer aggregate ------------------------------------------------------


def test_creator_payouts_footer_aggregates_when_payouts_present() -> None:
    cites = [
        _cite(handle="a", payout=0.005, wallet="7xKXabcdef9Lm"),
        _cite(handle="b", payout=0.005, wallet="3pMrabcduV8X"),
        _cite(handle="c", payout=0.005, wallet="9xKpabcdaF2Q"),
    ]
    out = _render(_creator_payouts_footer(cites, accent="cyan"))
    assert "Creator payouts" in out
    assert "$0.0150" in out
    assert "3 creators" in out


def test_creator_payouts_footer_singular_label_for_one_creator() -> None:
    cites = [_cite(handle="solo", payout=0.01)]
    out = _render(_creator_payouts_footer(cites, accent="cyan"))
    assert "1 creator" in out
    assert "creators" not in out  # plural form must not appear


# --- Null fields render unchanged -----------------------------------------


def test_citations_with_null_creator_fields_render_no_sub_line() -> None:
    cites = [_cite(url="https://example.com/x")]
    out = _render(_citations_renderable(cites, accent="cyan"))
    assert "@" not in out
    assert "paid" not in out


def test_creator_payouts_footer_returns_none_when_no_payouts() -> None:
    cites = [_cite(url="https://example.com/x")]  # all creator fields None
    assert _creator_payouts_footer(cites, accent="cyan") is None


def test_creator_payouts_footer_ignores_handle_only_citations() -> None:
    # Handle present but no payout — footer is about payouts, not handles.
    cites = [_cite(handle="just-credited")]
    assert _creator_payouts_footer(cites, accent="cyan") is None


# --- Wallet truncation ----------------------------------------------------


def test_truncate_wallet_long() -> None:
    assert _truncate_wallet("7xKXabcdefghijklmnop9Lm") == "7xKX…p9Lm"


def test_truncate_wallet_short_unchanged() -> None:
    assert _truncate_wallet("short") == "short"
