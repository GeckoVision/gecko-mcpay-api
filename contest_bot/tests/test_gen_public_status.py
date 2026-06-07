"""Public Status generator — publishes only ✅-live rows, leaks no internals.

Asserts on a tiny in-memory TRUTH_MAP fixture (no I/O, no network):
  * ONLY ✅ live rows appear,
  * 🟢 / 🟡 / ⬜ rows are dropped (internal hedges stay internal),
  * NO test-file paths leak,
  * NO internal Notes leak,
  * --check detects staleness.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gen_public_status.py"
_spec = importlib.util.spec_from_file_location("gen_public_status", _SCRIPT)
assert _spec and _spec.loader
gps = importlib.util.module_from_spec(_spec)
sys.modules["gen_public_status"] = gps
_spec.loader.exec_module(gps)


FIXTURE = """# Gecko — Truth Map

## Status legend
| Badge | Meaning | Bar |
|---|---|---|
| `✅ live` | Works | a test passes |

## Control plane API (`contest_bot/agent_api.py`)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| `GET /healthz` | ✅ live | `contest_bot/tests/test_e2e_app_surface.py` | |
| `GET /market-temp` | ✅ live | `contest_bot/tests/test_market_temp.py` | risk-on/off read |
| Something pending | 🟢 pending | `contest_bot/tests/test_x.py` | in a PR |

## Profit vault
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Vault deposit gate (deny-default) | ✅ live | `contest_bot/tests/test_vault_flow.py` | secret-note |
| **Real-money execution at scale** | 🟡 partial | — | manual; founder-gated |

## Arena (based.bid)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Survival board (bucketed bands) | ✅ live | `contest_bot/tests/test_arena_score.py` | no public raw floats |
| Read API over real based.bid tokens | ⬜ planned | — | needs discovery |
"""


def _parse():
    return gps.parse_live(FIXTURE)


def test_only_live_rows_collected():
    sections = dict(_parse())
    caps = {c for caps in sections.values() for c in caps}
    assert "GET /healthz" in caps
    assert "GET /market-temp" in caps
    assert "Vault deposit gate (deny-default)" in caps
    assert "Survival board (bucketed bands)" in caps
    # bold stripped on a live cap
    assert "Real-money execution at scale" not in caps  # 🟡 dropped anyway
    # exactly the 4 live caps, nothing else
    assert len(caps) == 4


def test_non_live_rows_dropped():
    caps = {c for caps in dict(_parse()).values() for c in caps}
    # 🟢 pending, 🟡 partial, ⬜ planned all excluded
    assert "Something pending" not in caps
    assert "Real-money execution at scale" not in caps
    assert "Read API over real based.bid tokens" not in caps


def test_no_test_paths_or_notes_leak_in_render():
    rendered = gps.render(_parse(), today="2026-01-01")
    assert ".py" not in rendered  # no test-file paths anywhere
    assert "test_" not in rendered
    assert "tests/" not in rendered
    # internal Notes must not leak
    assert "secret-note" not in rendered
    assert "founder-gated" not in rendered
    assert "risk-on/off read" not in rendered


def test_sections_grouped_with_public_titles():
    sections = dict(_parse())
    assert "Control plane" in sections
    assert "Profit vault" in sections
    assert "Arena" in sections
    # the brand line + count callout are present
    rendered = gps.render(_parse(), today="2026-01-01")
    assert "verified by automated tests" in rendered
    assert "**4 verified capabilities**" in rendered


def test_check_detects_staleness(tmp_path):
    rendered = gps.render(_parse(), today="2026-01-01")
    out = tmp_path / "status.mdx"
    out.write_text(rendered, encoding="utf-8")
    # identical body (different date footer) -> still up to date
    fresh = gps.render(_parse(), today="2099-12-31")
    assert gps._strip_generated_line(fresh).strip() == gps._strip_generated_line(rendered).strip()
    # a real content drift IS detected
    drifted = rendered.replace("GET /healthz", "GET /CHANGED")
    assert gps._strip_generated_line(drifted).strip() != gps._strip_generated_line(rendered).strip()
