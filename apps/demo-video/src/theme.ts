// Brand tokens — derived from verdict-still.png + trade-terminal.png
// Dark navy backdrop, mint accent (ACT pill), magenta/red for dissent, soft cyan citations.

export const COLORS = {
  bg: "#0B0F14",
  bgPanel: "#11161D",
  bgRaised: "#161C25",
  border: "#1F2733",

  text: "#E7ECF3",
  textMuted: "#9AA4B2",
  textDim: "#5F6A78",

  mint: "#22E3A6", // ACT pill / confidence bar / success / running
  mintDim: "#0E5A44",
  magenta: "#E94560", // DISSENT / action bullet
  amber: "#F5A524", // defer
  cyan: "#67E8F9", // citations / identifiers
  purple: "#A78BFA", // solana / advisor mode hint
} as const;

export const FONT = {
  display: '"Inter", system-ui, -apple-system, sans-serif',
  mono: '"JetBrains Mono", "Fira Code", "SF Mono", Menlo, monospace',
} as const;

// 30fps
export const FPS = 30;

// Scene durations in frames (each scene's own duration; transitions overlap)
export const SCENES = {
  title: 150, // 5s
  prompt1: 750, // 25s — types prompt 1 + reveals verdict
  chainProof: 300, // 10s
  prompt2: 750, // 25s — types prompt 2 + reveals deploy output
  prompt3: 750, // 25s — types prompt 3 + reveals reverdict
  moatStrip: 450, // 15s
  endCard: 300, // 10s
} as const;

export const TRANSITION = 18; // 0.6s cross-fade

// Total = sum(scenes) - transition * (n-1) overlap
// 150+750+300+750+750+450+300 = 3450; 6 transitions × 18 = 108 overlap
// duration = 3450 - 108 = 3342 frames ≈ 111.4s
export const DURATION_FRAMES =
  SCENES.title +
  SCENES.prompt1 +
  SCENES.chainProof +
  SCENES.prompt2 +
  SCENES.prompt3 +
  SCENES.moatStrip +
  SCENES.endCard -
  TRANSITION * 6;
