// WeeklyUpdate timing — 7 beats @ 30fps, 1800 frames total (60.0s).
// Boundaries are LOCKED per the weekly-update spec. Do not improvise.
import { FPS } from "../theme";

export const WEEKLY_FRAMES = 1800; // 60.0s @ 30fps

// [from, durationInFrames] per beat. Boundaries match the spec exactly.
export const BEATS = {
  title: { from: 0, dur: 120 }, //    0–120   · 0:00–0:04
  preContest: { from: 120, dur: 270 }, // 120–390  · 0:04–0:13
  reckoning: { from: 390, dur: 360 }, //  390–750  · 0:13–0:25
  reframe: { from: 750, dur: 240 }, //    750–990  · 0:25–0:33
  validation: { from: 990, dur: 360 }, // 990–1350 · 0:33–0:45
  roadmap: { from: 1350, dur: 270 }, //  1350–1620 · 0:45–0:54
  endCard: { from: 1620, dur: 180 }, //  1620–1800 · 0:54–1:00
} as const;

// Sanity: sum of durations must equal WEEKLY_FRAMES (non-overlapping beats).
export const _BEATS_SUM =
  BEATS.title.dur +
  BEATS.preContest.dur +
  BEATS.reckoning.dur +
  BEATS.reframe.dur +
  BEATS.validation.dur +
  BEATS.roadmap.dur +
  BEATS.endCard.dur;

export { FPS };
