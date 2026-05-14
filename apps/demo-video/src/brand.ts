// DemoV2 brand tokens — extension of theme.ts for the new 4-frame demo.
// Matches the existing demo keyframe style: stark dark editorial, mint accent.
export { COLORS, FONT, FPS } from "./theme";

// DemoV2 totals: 1:45 = 105s @ 30fps = 3150 frames
export const DEMO_V2_FRAMES = 3150;

// Per-frame durations (in frames @ 30fps)
export const V2_TIMING = {
  title: 150, // 0-5s
  query: 450, // 5-20s
  panel: 750, // 20-45s
  verdict: 750, // 45-70s
  defer: 750, // 70-95s
  endCard: 300, // 95-105s
} as const;

// Cumulative starts
export const V2_STARTS = {
  title: 0,
  query: V2_TIMING.title,
  panel: V2_TIMING.title + V2_TIMING.query,
  verdict: V2_TIMING.title + V2_TIMING.query + V2_TIMING.panel,
  defer:
    V2_TIMING.title + V2_TIMING.query + V2_TIMING.panel + V2_TIMING.verdict,
  endCard:
    V2_TIMING.title +
    V2_TIMING.query +
    V2_TIMING.panel +
    V2_TIMING.verdict +
    V2_TIMING.defer,
} as const;
