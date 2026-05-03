"""Program-judges corpus + skill.md draft synthesis (S21-JUDGE-CORPUS-01).

Public surface for the supply side of the program-judges wedge — see
``docs/strategy/program-judges-wedge.md``. Three operations:

- :func:`ingest_judge` — fetch tweets for one handle via twit.sh and
  persist as ``judge_corpus`` entries in Mongo (one collection per
  process, dedup by ``tweet_id``).
- :func:`load_corpus` — read all stored tweets for a handle, sorted
  newest-first.
- :func:`synth_skill_md` — produce a draft markdown skill file from a
  judge's corpus, using the ``judge_synth`` prompt in v5.5.

The judge corpus lives OUTSIDE any ``session_id`` — it accumulates
across runs and is queried by handle, not session. We write to a
dedicated ``gecko_rag.judge_corpus`` Mongo collection rather than the
``chunks`` table so the ``session_id`` NOT NULL constraint isn't
violated and so the corpus's lifecycle (operator-driven, weekly
re-ingest) doesn't tangle with session GC.
"""

from __future__ import annotations

from gecko_core.judges.colosseum import (
    COLOSSEUM_DATASET,
    WEB3_ACCELERATORS_DATASET,
    CalibrationIngestResult,
    calibration_corpus_id,
    ingest_colosseum,
    ingest_colosseum_feedback_posts,
    ingest_single_judge_file,
    ingest_web3_accelerators,
    load_calibration_chunks,
    render_calibration_block,
)
from gecko_core.judges.corpus import (
    JudgeTweet,
    delete_corpus,
    ingest_judge,
    load_corpus,
)
from gecko_core.judges.synth import format_skill_md, synth_skill_md

__all__ = [
    "COLOSSEUM_DATASET",
    "WEB3_ACCELERATORS_DATASET",
    "CalibrationIngestResult",
    "JudgeTweet",
    "calibration_corpus_id",
    "delete_corpus",
    "format_skill_md",
    "ingest_colosseum",
    "ingest_colosseum_feedback_posts",
    "ingest_judge",
    "ingest_single_judge_file",
    "ingest_web3_accelerators",
    "load_calibration_chunks",
    "load_corpus",
    "render_calibration_block",
    "synth_skill_md",
]
