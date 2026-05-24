"""Phase V Feature conformers built on the structure primitives (Gecko lab, Phase 1).

These wrap contest_bot/features/structure.py as Phase V `Feature`s
(compute(candles, i) -> float, strictly causal). They are FRAMED the way the
prior Phase-1 de-risk run found works:

  * VETO signals (subtractive) — penalize entries INTO overhead resistance and
    MID-RANGE chop. The prior null was that "structure CONFIRMS direction"
    (require HH/HL up) is anti-predictive; the usable signal is subtractive.
  * a ROOM-TO-RUN / R:R GATE — reward entries whose headroom to the next
    resistance is >= ~2x the round-trip fee. This is the direct lever on gross
    edge: only take entries with enough room to clear fees.
  * a STRUCTURE-NOT-DOWN veto — avoid DOWN-structure breakouts (the prior run's
    one mildly-positive structural thread), NOT "require UP".

NOT included by design: a "structure confirms the breakout direction" feature
(require UP) — that is the axis the prior run falsified.

CANDLE SHAPE
  The Phase V Feature protocol passes the enriched dict-of-lists
  (candles["high"], candles["low"], candles["close"] aligned ascending). These
  conformers slice those lists and call the structure primitives. Every read is
  on candles[:i+1] (the primitives enforce the j+k confirmation lag), so the
  lookahead trap passes by construction.

The score convention is "higher = more bullish / more take-able", consistent
with feature_validation's tercile edge estimator. Each gate also exposes a
boolean predicate (`passes`) so the acceptance-gate harness can build the
SELECTED ("act") subset for the net-EV / gross-edge / N_eff gates.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import structure as st

# Default DEX round-trip fee (%). 2x this is the R:R bar the room gate enforces
# and the acceptance gate's economic bar. Central live read is 0.75% RT.
DEFAULT_FEE_RT = 0.75
ROOM_FEE_MULTIPLE = 2.0  # require room >= 2x RT fee = the gross-edge bar

# A large finite sentinel for "open sky" room (no overhead resistance). Open sky
# is the MOST room, so it must score above any finite room. Chosen well above any
# realistic % room-to-resistance on a meme tape.
OPEN_SKY_ROOM_PCT = 100.0

# Mid-range dead-zone half-width around range-position 0.5. An entry whose
# range-position is within [0.5 - w, 0.5 + w] is "mid-range chop" and vetoed.
MID_RANGE_HALF_WIDTH = 0.15


def _hlc(candles: dict) -> tuple[list[float], list[float], list[float]]:
    return candles["high"], candles["low"], candles["close"]


# ── Feature 1: overhead room (continuous, subtractive) ──────────────
@dataclass
class OverheadRoomFeature:
    """Score = % room to the next resistance above the close (open sky = max).

    This is the CONTINUOUS room-to-run measure. Low score = breaking out straight
    into a ceiling (the entries the veto wants to subtract); high score / open sky
    = headroom to run. Strictly causal."""

    k: int = st.DEFAULT_PIVOT_K
    cluster_pct: float = st.DEFAULT_CLUSTER_PCT
    name: str = "overhead_room_pct"

    def compute(self, candles: dict, i: int) -> float:
        highs, lows, closes = _hlc(candles)
        room = st.distance_to_next_resistance(highs, lows, closes, i, self.k, self.cluster_pct)
        return OPEN_SKY_ROOM_PCT if room is None else room


# ── Feature 2: room-to-run / R:R gate (the direct gross-edge lever) ─
@dataclass
class RoomToRunGate:
    """Binary R:R gate: 1.0 if overhead room >= room_multiple x round-trip fee,
    else 0.0. This is the explicit gross-edge lever — only take entries with
    enough headroom to clear fees. Open sky always passes (max room).

    `passes(candles, i)` is the predicate the acceptance harness uses to build
    the SELECTED subset. Strictly causal."""

    fee_rt: float = DEFAULT_FEE_RT
    room_multiple: float = ROOM_FEE_MULTIPLE
    k: int = st.DEFAULT_PIVOT_K
    cluster_pct: float = st.DEFAULT_CLUSTER_PCT
    name: str = "room_to_run_gate"

    @property
    def threshold_pct(self) -> float:
        return self.room_multiple * self.fee_rt

    def passes(self, candles: dict, i: int) -> bool:
        highs, lows, closes = _hlc(candles)
        room = st.distance_to_next_resistance(highs, lows, closes, i, self.k, self.cluster_pct)
        return room is None or room >= self.threshold_pct

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


# ── Feature 3: not-into-resistance veto (subtractive) ───────────────
@dataclass
class NotIntoResistanceVeto:
    """Veto entries breaking out directly INTO overhead resistance.

    passes = room is open sky OR >= min_room_pct. compute returns the room when it
    passes (continuous reward for headroom) and 0.0 when vetoed. This is the pure
    subtractive framing: it removes the into-the-ceiling entries the prior run
    flagged. Strictly causal."""

    min_room_pct: float = ROOM_FEE_MULTIPLE * DEFAULT_FEE_RT
    k: int = st.DEFAULT_PIVOT_K
    cluster_pct: float = st.DEFAULT_CLUSTER_PCT
    name: str = "not_into_resistance_veto"

    def _room(self, candles: dict, i: int) -> float | None:
        highs, lows, closes = _hlc(candles)
        return st.distance_to_next_resistance(highs, lows, closes, i, self.k, self.cluster_pct)

    def passes(self, candles: dict, i: int) -> bool:
        room = self._room(candles, i)
        return room is None or room >= self.min_room_pct

    def compute(self, candles: dict, i: int) -> float:
        room = self._room(candles, i)
        if room is None:
            return OPEN_SKY_ROOM_PCT
        return room if room >= self.min_room_pct else 0.0


# ── Feature 4: not-mid-range veto (subtractive, chop dead-zone) ─────
@dataclass
class NotMidRangeVeto:
    """Veto MID-RANGE chop entries. An entry whose range-position is within the
    dead-zone around 0.5 is vetoed (chop, no edge); an entry near a range boundary
    (breaking out, or bouncing off support) passes.

    score = |range_position - 0.5| (distance from mid-range; higher = nearer a
    boundary = more take-able). passes = range-position outside the dead-zone.
    Undefined range (None) -> treated as NOT mid-range (passes, score = max), since
    no range means no chop box to be stuck in. Strictly causal."""

    half_width: float = MID_RANGE_HALF_WIDTH
    k: int = st.DEFAULT_PIVOT_K
    name: str = "not_mid_range_veto"

    def _pos(self, candles: dict, i: int) -> float | None:
        highs, lows, closes = _hlc(candles)
        return st.range_position(highs, lows, closes, i, self.k)

    def passes(self, candles: dict, i: int) -> bool:
        pos = self._pos(candles, i)
        if pos is None:
            return True  # no range box -> not stuck mid-range
        return abs(pos - 0.5) > self.half_width

    def compute(self, candles: dict, i: int) -> float:
        pos = self._pos(candles, i)
        if pos is None:
            return 0.5  # max distance-from-mid (no box)
        return abs(pos - 0.5)


# ── Feature 5: structure-not-down veto (avoid DOWN, not require UP) ─
@dataclass
class StructureNotDownVeto:
    """Veto DOWN-structure breakouts. score = 1.0 unless market structure is DOWN
    (LH+LL), in which case 0.0. This is the prior run's one mildly-positive
    structural thread: AVOID down-structure, NOT require an up-structure (which was
    anti-predictive). Strictly causal."""

    k: int = st.DEFAULT_PIVOT_K
    name: str = "structure_not_down_veto"

    def passes(self, candles: dict, i: int) -> bool:
        highs, lows, _closes = _hlc(candles)
        return st.market_structure(highs, lows, i, self.k) != "DOWN"

    def compute(self, candles: dict, i: int) -> float:
        return 1.0 if self.passes(candles, i) else 0.0


# ── Combined veto+gate (room AND not-down AND not-mid-range) ────────
@dataclass
class StructureStackGate:
    """The full subtractive stack: room-to-run R:R gate AND not-down structure AND
    not-mid-range. compute returns the room value when ALL pass, else 0.0. This is
    the candidate "act" set the gross-edge question is really about. Strictly
    causal."""

    fee_rt: float = DEFAULT_FEE_RT
    room_multiple: float = ROOM_FEE_MULTIPLE
    half_width: float = MID_RANGE_HALF_WIDTH
    k: int = st.DEFAULT_PIVOT_K
    cluster_pct: float = st.DEFAULT_CLUSTER_PCT
    name: str = "structure_stack_gate"

    def __post_init__(self) -> None:
        self._room = RoomToRunGate(
            fee_rt=self.fee_rt,
            room_multiple=self.room_multiple,
            k=self.k,
            cluster_pct=self.cluster_pct,
        )
        self._notdown = StructureNotDownVeto(k=self.k)
        self._notmid = NotMidRangeVeto(half_width=self.half_width, k=self.k)

    def passes(self, candles: dict, i: int) -> bool:
        return (
            self._room.passes(candles, i)
            and self._notdown.passes(candles, i)
            and self._notmid.passes(candles, i)
        )

    def compute(self, candles: dict, i: int) -> float:
        if not self.passes(candles, i):
            return 0.0
        highs, lows, closes = _hlc(candles)
        room = st.distance_to_next_resistance(highs, lows, closes, i, self.k, self.cluster_pct)
        return OPEN_SKY_ROOM_PCT if room is None else room


__all__ = [
    "DEFAULT_FEE_RT",
    "ROOM_FEE_MULTIPLE",
    "NotIntoResistanceVeto",
    "NotMidRangeVeto",
    "OverheadRoomFeature",
    "RoomToRunGate",
    "StructureNotDownVeto",
    "StructureStackGate",
]
