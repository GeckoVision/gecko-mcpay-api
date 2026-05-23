// WeeklyUpdate timing — product-forward recut @ 30fps, 1800 frames total (60.0s).
// "Less ads, more building": the live studio walkthrough gets the MOST time.
import { FPS } from "../theme";

export const WEEKLY_FRAMES = 1800; // 60.0s @ 30fps

// [from, durationInFrames] per beat. The studio beat is the centerpiece (18s).
export const BEATS = {
  title: { from: 0, dur: 90 }, //         0–90    · 0:00–0:03  title
  preContest: { from: 90, dur: 210 }, //  90–300   · 0:03–0:10  contest v1 (real, restricted)
  reckoning: { from: 300, dur: 240 }, //  300–540  · 0:10–0:18  the reckoning (real numbers)
  studio: { from: 540, dur: 540 }, //     540–1080 · 0:18–0:36  THE WORKING BOT (centerpiece)
  validation: { from: 1080, dur: 270 }, //1080–1350· 0:36–0:45  the validation
  roadmap: { from: 1350, dur: 240 }, //  1350–1590 · 0:45–0:53  architecture
  endCard: { from: 1590, dur: 210 }, //  1590–1800 · 0:53–1:00  end card + waitlist CTA
} as const;

// Sanity: sum of durations must equal WEEKLY_FRAMES (non-overlapping beats).
export const _BEATS_SUM =
  BEATS.title.dur +
  BEATS.preContest.dur +
  BEATS.reckoning.dur +
  BEATS.studio.dur +
  BEATS.validation.dur +
  BEATS.roadmap.dur +
  BEATS.endCard.dur;

export { FPS };
