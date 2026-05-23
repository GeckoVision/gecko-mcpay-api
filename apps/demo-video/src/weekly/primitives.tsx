import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

// Shared primitives for the WeeklyUpdate beats. Stark dark editorial, mint accent,
// monospace/terminal-native. Burn-in captions are the spine: the video must read
// fully with sound off.

// Spring fade-in. Returns 0..1. Use for opacity + small slide offsets.
export const useFade = (delay = 0, dur = 18): number => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({
    frame: frame - delay,
    fps,
    config: { damping: 200 },
    durationInFrames: dur,
  });
};

// Soft fade at the tail of a beat so cuts are calm, not hard.
export const useBeatTail = (beatDur: number, fadeFrames = 12): number => {
  const frame = useCurrentFrame();
  return interpolate(
    frame,
    [beatDur - fadeFrames, beatDur],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
};

// Eyebrow / kicker label — uppercase, tracked, muted. Terminal-native section marker.
export const Eyebrow: React.FC<{
  children: React.ReactNode;
  color?: string;
  opacity?: number;
}> = ({ children, color = COLORS.textMuted, opacity = 1 }) => (
  <div
    style={{
      fontFamily: FONT.mono,
      fontSize: 18,
      letterSpacing: 6,
      textTransform: "uppercase",
      color,
      opacity,
    }}
  >
    {children}
  </div>
);

// Burn-in caption line. The load-bearing text — large, high contrast, mono.
export const Caption: React.FC<{
  children: React.ReactNode;
  size?: number;
  color?: string;
  opacity?: number;
  weight?: number;
  mono?: boolean;
  maxWidth?: number;
}> = ({
  children,
  size = 52,
  color = COLORS.text,
  opacity = 1,
  weight = 600,
  mono = false,
  maxWidth = 1400,
}) => (
  <div
    style={{
      fontFamily: mono ? FONT.mono : FONT.display,
      fontSize: size,
      fontWeight: weight,
      lineHeight: 1.25,
      letterSpacing: mono ? 0 : -0.5,
      color,
      opacity,
      maxWidth,
    }}
  >
    {children}
  </div>
);

// Blinking terminal caret.
export const Caret: React.FC<{ color?: string }> = ({ color = COLORS.mint }) => {
  const frame = useCurrentFrame();
  const on = Math.floor(frame / 15) % 2 === 0;
  return <span style={{ opacity: on ? 1 : 0, color }}>▌</span>;
};
