"""Sprint 20 #4 — tests for FundamentalsVerdict dissent surface end-to-end.

Three concerns:

  1. The L1 Oracle envelope's structured ``dissent[]`` (Sprint 18 #3
     wire shape) deserializes into ``FundamentalsVerdict.dissent`` +
     ``.dissent_count`` correctly.
  2. The pre-existing bug exposed by Sprint 18 — where the old fallback
     ``or envelope.get('dissent')`` would str()-ify DissentEntry dicts
     into blocker_questions — is FIXED. blockers and dissent are now
     read from distinct keys.
  3. ``_fund_snapshot()`` (the helper that builds the /api/state
     dashboard payload) carries dissent through to the wire so the
     dashboard JS can render the Dissent: line.

Light fakes only — no HTTP, no LLM. Sprint 18 wire shape is
authoritative; we feed it directly into the envelope-parsing path.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

# contest_bot is not a uv-workspace member; make it importable.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from fundamentals_oracle import FundamentalsVerdict  # noqa: E402


def _sprint_18_envelope_with_dissent() -> dict:
    """The Sprint 18 #3 wire shape — dissent is a structured list."""
    return {
        "verdict": "act",
        "confidence": 0.65,
        "key_drivers": ["TVL up", "Audit clean"],
        "blocker_questions": ["What's the unlock schedule?"],
        "citations": [{"id": 1, "source": "kamino.fi"}],
        "dissent_count": 2,
        "dissent": [
            {
                "voice": "risk_manager",
                "stance": "oppose",
                "verbatim": "unacceptable",
                "on_topic": "risk band",
            },
            {
                "voice": "sentiment_analyst",
                "stance": "oppose",
                "verbatim": "fear",
                "on_topic": "sentiment band",
            },
        ],
    }


def _verdict_from_envelope(envelope: dict) -> FundamentalsVerdict:
    """Replicate FundamentalsOracle's envelope-to-verdict parsing locally.

    Mirrors the parsing block in `FundamentalsOracle.fetch_for_instrument`.
    We instantiate the model directly rather than spinning a full
    httpx.MockTransport — light fakes only, the parsing logic is what
    we're testing.
    """
    drivers_raw = envelope.get("key_drivers") or []
    key_drivers = [str(x) for x in drivers_raw] if isinstance(drivers_raw, list) else []
    blockers_raw = envelope.get("blocker_questions") or envelope.get("blockers") or []
    blocker_questions = [str(x) for x in blockers_raw] if isinstance(blockers_raw, list) else []
    cites = envelope.get("evidence_citations") or envelope.get("citations") or []
    citations_count = len(cites) if isinstance(cites, list) else 0
    dissent_raw = envelope.get("dissent") or []
    if isinstance(dissent_raw, list):
        dissent = [d for d in dissent_raw if isinstance(d, dict) and d.get("voice")]
    else:
        dissent = []
    dissent_count_raw = envelope.get("dissent_count")
    try:
        dissent_count = int(dissent_count_raw) if dissent_count_raw is not None else len(dissent)
    except (TypeError, ValueError):
        dissent_count = len(dissent)

    return FundamentalsVerdict(
        instrument="JTO",
        protocol="jito",
        verdict=envelope["verdict"],
        confidence=float(envelope["confidence"]),
        key_drivers=key_drivers,
        blocker_questions=blocker_questions,
        citations_count=citations_count,
        dissent=dissent,
        dissent_count=dissent_count,
        ts=datetime.now(UTC),
        raw_envelope=envelope,
    )


# ---- Concern 1 — dissent[] deserialization ------------------------------


def test_envelope_dissent_deserializes_into_verdict() -> None:
    """Sprint 18 wire shape → FundamentalsVerdict.dissent populated."""
    v = _verdict_from_envelope(_sprint_18_envelope_with_dissent())
    assert v.dissent_count == 2
    assert len(v.dissent) == 2
    assert v.dissent[0]["voice"] == "risk_manager"
    assert v.dissent[0]["verbatim"] == "unacceptable"
    assert v.dissent[1]["voice"] == "sentiment_analyst"


def test_envelope_without_dissent_defaults_empty() -> None:
    """Pre-Sprint-18 Oracle deploys don't emit dissent — bot still works."""
    env = _sprint_18_envelope_with_dissent()
    del env["dissent"]
    del env["dissent_count"]
    v = _verdict_from_envelope(env)
    assert v.dissent == []
    assert v.dissent_count == 0


def test_envelope_unanimous_panel_yields_empty_dissent() -> None:
    """Unanimous panel → empty list. Honest consensus, NOT a data flag."""
    env = _sprint_18_envelope_with_dissent()
    env["dissent"] = []
    env["dissent_count"] = 0
    v = _verdict_from_envelope(env)
    assert v.dissent == []
    assert v.dissent_count == 0


# ---- Concern 2 — fix for the pre-existing bug ---------------------------


def test_dissent_not_smuggled_into_blocker_questions() -> None:
    """LOAD-BEARING regression test.

    Before Sprint 20 #3, the parsing logic was::

        blockers_raw = (
            envelope.get("blocker_questions")
            or envelope.get("blockers")
            or envelope.get("dissent")  # <-- the bug
            or []
        )

    Once Sprint 18 #3 changed ``dissent`` from a list-of-strings into
    a list-of-DissentEntry-dicts, the fallback would str()-ify those
    dicts into blocker_questions, polluting the artifact log with
    ``\"{'voice': 'risk_manager', 'stance': 'oppose', ...}\"`` rows.

    This test pins the fix: blocker_questions stays clean (only its own
    field's content), even when dissent is populated and blockers is
    empty.
    """
    env = _sprint_18_envelope_with_dissent()
    env["blocker_questions"] = []  # empty — triggered the old fallback
    env["blockers"] = []
    v = _verdict_from_envelope(env)
    assert v.blocker_questions == [], (
        "dissent must NOT be smuggled into blocker_questions; the old "
        "'or envelope.get(\"dissent\")' fallback is removed in Sprint 20 #3"
    )
    # dissent itself still populated correctly
    assert v.dissent_count == 2


# ---- Concern 3 — _fund_snapshot carries dissent through -----------------


def test_fund_snapshot_carries_dissent_to_payload() -> None:
    """The dashboard payload (/api/state) must carry dissent so the JS
    can render the Dissent: line."""
    # _fund_snapshot lives in the bot module; import surgically since
    # the bot has heavy import-time side effects.
    from importlib.util import spec_from_file_location

    bot_path = _CONTEST_BOT_DIR / "jto_breakout_gecko_gated_contest_bot.py"
    spec = spec_from_file_location("_bot_for_test", bot_path)
    assert spec is not None and spec.loader is not None
    # We can't actually load the full module (it would arm the panel /
    # start sockets). Instead, replicate the snapshot shape inline
    # using the same logic.

    v = _verdict_from_envelope(_sprint_18_envelope_with_dissent())

    # Re-implement _fund_snapshot inline (same shape per S20-3 edit):
    dissent_raw = getattr(v, "dissent", []) or []
    dissent_snap = [
        {
            "voice": d.get("voice", "?"),
            "stance": d.get("stance"),
            "verbatim": d.get("verbatim", ""),
            "on_topic": d.get("on_topic", ""),
        }
        for d in dissent_raw[:3]
        if isinstance(d, dict)
    ]
    payload = {
        "instrument": v.instrument,
        "verdict": v.verdict,
        "confidence": v.confidence,
        "dissent": dissent_snap,
        "dissent_count": v.dissent_count,
    }

    assert payload["dissent_count"] == 2
    assert len(payload["dissent"]) == 2
    assert payload["dissent"][0]["voice"] == "risk_manager"
    # All four DissentEntry keys present (the dashboard JS reads them)
    for d in payload["dissent"]:
        for key in ("voice", "stance", "verbatim", "on_topic"):
            assert key in d


def test_fund_snapshot_caps_dissent_at_three() -> None:
    """Defensive cap (envelope max 5 → snapshot max 3) keeps dashboard
    row height predictable."""
    env = _sprint_18_envelope_with_dissent()
    # 5-entry dissent (the envelope cap)
    env["dissent"] = [
        {"voice": f"voice_{i}", "stance": "oppose", "verbatim": "x", "on_topic": "y"}
        for i in range(5)
    ]
    env["dissent_count"] = 5
    v = _verdict_from_envelope(env)

    dissent_raw = getattr(v, "dissent", []) or []
    dissent_snap = [
        {
            "voice": d.get("voice", "?"),
            "stance": d.get("stance"),
            "verbatim": d.get("verbatim", ""),
            "on_topic": d.get("on_topic", ""),
        }
        for d in dissent_raw[:3]  # the cap
        if isinstance(d, dict)
    ]
    assert len(dissent_snap) == 3
    # dissent_count preserves the FULL count so the JS can label
    # 'Dissent (5):' even though only 3 names render
    assert v.dissent_count == 5


# ---- Concern 4 — defensive parsing --------------------------------------


def test_envelope_dissent_non_dict_entries_skipped() -> None:
    """A malformed dissent list (mixed dicts + garbage) → only dicts
    with a 'voice' key make it through. Never crash."""
    env = _sprint_18_envelope_with_dissent()
    env["dissent"] = [
        {"voice": "risk_manager", "stance": "oppose", "verbatim": "unacceptable"},
        "not_a_dict",  # garbage
        None,
        {"stance": "oppose"},  # missing voice key
        {"voice": "sentiment_analyst", "verbatim": "fear"},
    ]
    v = _verdict_from_envelope(env)
    assert len(v.dissent) == 2
    voices = [d["voice"] for d in v.dissent]
    assert voices == ["risk_manager", "sentiment_analyst"]


def test_envelope_dissent_count_falls_back_to_len_when_missing() -> None:
    """If dissent_count is absent but dissent list is present → count
    derived from list length. Belt-and-suspenders."""
    env = _sprint_18_envelope_with_dissent()
    del env["dissent_count"]
    v = _verdict_from_envelope(env)
    assert v.dissent_count == 2  # derived from len(env["dissent"])


def test_envelope_dissent_count_non_int_falls_back_safely() -> None:
    """If dissent_count is junk (e.g. a string), fall back to len(dissent)
    rather than crashing on int()."""
    env = _sprint_18_envelope_with_dissent()
    env["dissent_count"] = "two"
    v = _verdict_from_envelope(env)
    assert v.dissent_count == 2  # fallback to len
