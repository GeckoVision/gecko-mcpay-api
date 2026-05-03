"""S21-JUDGE-CORPUS-01 — judge corpus + skill.md synth tests.

Three concerns:

1. ``TwitshSource.fetch_user_tweets`` mock test — single-call shape and
   stop-on-no-new-tweets behaviour against a respx router.
2. ``judge_corpus`` is in ``ProviderKind`` — guarded by the existing
   drift test (``test_provider_kind_consistency``); this file just
   imports the Literal so a mistake here surfaces as a test-collection
   error, not a silent miss.
3. ``format_skill_md`` is a pure function — fixture envelope in,
   markdown out, schema sections present.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from gecko_core.judges.synth import JudgeSynthEnvelope, format_skill_md
from gecko_core.sources.twit_sh import ASSUMED_PER_CALL_USD, TwitshSource
from gecko_core.sources.types import PROVIDER_KINDS

# ---------------------------------------------------------------------------
# ProviderKind taxonomy guard
# ---------------------------------------------------------------------------


def test_provider_kind_includes_judge_corpus() -> None:
    """Pattern A: judge_corpus must be in the canonical Literal.

    The full SQL-vs-Python drift test lives in
    ``test_provider_kind_consistency``; this is a tiny sanity probe so
    a mistake in this file's source surfaces as a test-collection error.
    """
    assert "judge_corpus" in PROVIDER_KINDS


# ---------------------------------------------------------------------------
# fetch_user_tweets
# ---------------------------------------------------------------------------


@pytest.fixture
def _force_live_x402(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("X402_MODE", "live")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)


_TWEET_ROWS = [
    {
        "id_str": "11111",
        "text": "Builders shipping V1 in 4 days beats builders shipping perfect V3 in 4 months.",
        "user": {"screen_name": "kukasolana"},
        "url": "https://x.com/kukasolana/status/11111",
        "created_at": "2026-04-30T12:00:00Z",
        "public_metrics": {"like_count": 42, "reply_count": 3, "retweet_count": 7},
    },
    {
        "id_str": "22222",
        "text": "Hard no on tokenomics-first hackathon decks. Show me the user.",
        "user": {"screen_name": "kukasolana"},
        "url": "https://x.com/kukasolana/status/22222",
        "created_at": "2026-04-29T10:00:00Z",
        "public_metrics": {"like_count": 18, "reply_count": 1, "retweet_count": 4},
    },
]
# Single-page response — no next_token so the loop stops after one call.
_USER_TWEETS_RESPONSE = {"tweets": _TWEET_ROWS}
# Multi-page response — carries next_token so a second call is made.
_USER_TWEETS_RESPONSE_P1 = {"tweets": _TWEET_ROWS, "meta": {"next_token": "tok_page2"}}


@pytest.mark.usefixtures("_force_live_x402")
async def test_fetch_user_tweets_normalizes_and_dedupes() -> None:
    """Single call returns normalized tweets with id_str carried through."""
    async with respx.mock(base_url="https://x402.twit.sh", assert_all_called=False) as router:
        router.get("/tweets/user").mock(
            return_value=httpx.Response(200, json=_USER_TWEETS_RESPONSE)
        )
        client = httpx.AsyncClient(base_url="https://x402.twit.sh")
        src = TwitshSource(http_client=client)
        # max_calls=1 — single page; no next_token in response.
        tweets, spent = await src.fetch_user_tweets("kukasolana", max_calls=1)
        await src.aclose()

    assert len(tweets) == 2
    assert tweets[0]["id_str"] == "11111"
    assert tweets[0]["author_handle"] == "@kukasolana"
    assert tweets[0]["engagement"]["likes"] == 42
    assert spent == pytest.approx(ASSUMED_PER_CALL_USD)


@pytest.mark.usefixtures("_force_live_x402")
async def test_fetch_user_tweets_stops_when_window_exhausted() -> None:
    """Pagination cursor present on page 1 → second call made; no new ids → stop.

    /tweets/user returns meta.next_token when more pages exist. The loop
    advances with the cursor; when the second response yields no new tweet
    ids (all already seen) the dedup guard fires and the loop exits.
    """
    call_count = {"n": 0}

    def _handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        # Page 1 carries a next_token; page 2 returns the same tweets
        # (simulates the window rotating back to the same results).
        if call_count["n"] == 1:
            return httpx.Response(200, json=_USER_TWEETS_RESPONSE_P1)
        return httpx.Response(200, json=_USER_TWEETS_RESPONSE)

    async with respx.mock(base_url="https://x402.twit.sh", assert_all_called=False) as router:
        router.get("/tweets/user").mock(side_effect=_handler)
        client = httpx.AsyncClient(base_url="https://x402.twit.sh")
        src = TwitshSource(http_client=client)
        tweets, spent = await src.fetch_user_tweets("kukasolana", max_calls=5)
        await src.aclose()

    # Two unique ids from page 1; page 2 adds nothing → break after 2 calls.
    assert len(tweets) == 2
    assert call_count["n"] == 2
    assert spent == pytest.approx(2 * ASSUMED_PER_CALL_USD)


# ---------------------------------------------------------------------------
# format_skill_md (pure function, no LLM)
# ---------------------------------------------------------------------------


def _envelope_fixture() -> JudgeSynthEnvelope:
    return JudgeSynthEnvelope(
        display_name="Kuka",
        voice_summary=(
            "Kuka pushes builders toward narrow V1 cuts and named first users. "
            "Public criticism focuses on tokenomics-first decks and unclear "
            "buyers. Frames hackathon judgments around 4-day shippability."
        ),
        cares_about=[
            "Named first user before V1 (2026-04-30)",
            "4-day V1 box (2026-04-30)",
            "Hard no on token-first decks (2026-04-29)",
            "UX over L1 narrative (2026-04-25)",
            "Concrete demo > slides (2026-04-22)",
        ],
        evaluation_lens=(
            "I look for one named user who would pay within 30 days. "
            "I push back when the deck leads with tokenomics or L1 choice "
            "before naming a buyer."
        ),
        hard_nos=[
            "Tokenomics-first decks (2026-04-29)",
            "Generic 'AI agent for X' framing (2026-04-27)",
            "No named first user (2026-04-30)",
        ],
        phrasings=[
            '"Show me the user." (2026-04-29)',
            '"4 days, one named buyer, one payment moment." (2026-04-30)',
            '"L1 choice is not a wedge." (2026-04-25)',
        ],
        open_questions=[
            "How do you weight team composition vs demo polish?",
            "What's the line between 'too early' and 'pivot'?",
            "Do you weight Solana-native judges differently?",
        ],
        insufficient_sections=[],
    )


def test_format_skill_md_contains_required_sections() -> None:
    md = format_skill_md(
        handle="kukasolana",
        envelope=_envelope_fixture(),
        n_tweets=12,
        oldest_date="2026-04-22",
        newest_date="2026-04-30",
        today="2026-05-02",
    )
    # Section headings.
    assert "# Kuka — Voice Draft (DRAFT, awaiting approval)" in md
    assert "## Voice summary" in md
    assert "## What this judge cares about" in md
    assert "## Evaluation lens (when reading a builder's pitch)" in md
    assert '## Hard "no"s' in md
    assert "## Phrasings & tone" in md
    assert "## Open questions for the judge" in md
    assert "## Provenance" in md
    # Status line.
    assert "DRAFT — pending review by @kukasolana" in md
    # Provenance fields.
    assert "Tweets ingested: 12" in md
    assert "2026-04-22 — 2026-04-30" in md
    assert "Generated: 2026-05-02" in md
    # Generator line uses gecko version, not a model name.
    assert "v0.1.6" in md
    assert "gpt-4o" not in md  # model names must not leak per CLAUDE.md
    # First-person evaluation lens preserved.
    assert "I look for one named user" in md


def test_format_skill_md_marks_insufficient_sections() -> None:
    env = _envelope_fixture()
    env.insufficient_sections = ["hard_nos", "phrasings"]
    env.hard_nos = []
    env.phrasings = []
    md = format_skill_md(
        handle="kauenet",
        envelope=env,
        n_tweets=3,
        oldest_date="2026-04-30",
        newest_date="2026-05-01",
        today="2026-05-02",
    )
    # Insufficient sections render the explicit placeholder.
    assert md.count("(insufficient corpus — re-ingest in 7 days)") >= 2
    # Open questions still present (mandatory section).
    assert "## Open questions for the judge" in md


def test_format_skill_md_open_questions_fallback_when_missing() -> None:
    env = _envelope_fixture()
    env.open_questions = []
    md = format_skill_md(
        handle="shimas_sol",
        envelope=env,
        n_tweets=5,
        oldest_date="2026-04-25",
        newest_date="2026-05-01",
        today="2026-05-02",
    )
    assert "(none surfaced — confirm with judge in person)" in md
