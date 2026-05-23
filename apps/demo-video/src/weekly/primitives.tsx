import {
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
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

// StudioShot — a real screenshot of the live bot framed in a terminal-style chrome
// with a slow Ken Burns drift. This is the "this is how it works" footage. The
// screenshots are crisp scale-2 PNGs; we present them at high contrast on dark.
export const StudioShot: React.FC<{
  asset: string; // relative to public/, e.g. "assets/studio/panel-indexes.png"
  // local frame within the parent Sequence used to drive the drift
  localFrame: number;
  zoomFrom?: number;
  zoomTo?: number;
  // pan offset (px) applied over the shot's life — subtle, documentary
  panX?: number;
  panY?: number;
  durFrames: number;
  // object-fit: "contain" shows the whole panel; "cover" fills (for crops)
  fit?: "contain" | "cover";
  // optional crop alignment when fit=cover
  align?: string;
  radius?: number;
}> = ({
  asset,
  localFrame,
  zoomFrom = 1.0,
  zoomTo = 1.06,
  panX = 0,
  panY = 0,
  durFrames,
  fit = "contain",
  align = "center",
  radius = 16,
}) => {
  const t = interpolate(localFrame, [0, durFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const scale = interpolate(t, [0, 1], [zoomFrom, zoomTo]);
  const tx = interpolate(t, [0, 1], [0, panX]);
  const ty = interpolate(t, [0, 1], [0, panY]);
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        overflow: "hidden",
        borderRadius: radius,
        border: `1px solid ${COLORS.border}`,
        background: COLORS.bgPanel,
        boxShadow: `0 24px 80px #00000060`,
      }}
    >
      <Img
        src={staticFile(asset)}
        style={{
          width: "100%",
          height: "100%",
          objectFit: fit,
          objectPosition: align,
          transform: `scale(${scale}) translate(${tx}px, ${ty}px)`,
          transformOrigin: "center",
          imageRendering: "auto",
        }}
      />
    </div>
  );
};

// Terminal window chrome: traffic-light dots + a mono title bar. Wraps a StudioShot.
export const TerminalFrame: React.FC<{
  title: string;
  badge?: string;
  badgeColor?: string;
  children: React.ReactNode;
}> = ({ title, badge, badgeColor = COLORS.mint, children }) => (
  <div
    style={{
      display: "flex",
      flexDirection: "column",
      width: "100%",
      height: "100%",
      borderRadius: 16,
      overflow: "hidden",
      border: `1px solid ${COLORS.border}`,
      background: COLORS.bg,
    }}
  >
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "14px 22px",
        background: COLORS.bgRaised,
        borderBottom: `1px solid ${COLORS.border}`,
      }}
    >
      <div style={{ display: "flex", gap: 8 }}>
        {["#FF5F56", "#FFBD2E", "#27C93F"].map((c) => (
          <span
            key={c}
            style={{ width: 12, height: 12, borderRadius: 99, background: c, opacity: 0.85 }}
          />
        ))}
      </div>
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: 18,
          color: COLORS.textMuted,
          letterSpacing: 1,
        }}
      >
        {title}
      </span>
      {badge && (
        <span
          style={{
            marginLeft: "auto",
            fontFamily: FONT.mono,
            fontSize: 14,
            letterSpacing: 2,
            textTransform: "uppercase",
            color: badgeColor,
            border: `1px solid ${badgeColor}`,
            borderRadius: 6,
            padding: "3px 10px",
          }}
        >
          {badge}
        </span>
      )}
    </div>
    <div style={{ flex: 1, position: "relative", minHeight: 0 }}>{children}</div>
  </div>
);

// PointerCaption — a labeled callout that points at the panel currently on screen.
// Burn-in (reads muted). Slides up + fades.
export const PointerCaption: React.FC<{
  localFrame: number;
  delay?: number;
  label: string;
  sub?: string;
  accent?: string;
}> = ({ localFrame, delay = 0, label, sub, accent = COLORS.mint }) => {
  const { fps } = useVideoConfig();
  const op = spring({
    frame: localFrame - delay,
    fps,
    config: { damping: 200 },
    durationInFrames: 16,
  });
  const y = interpolate(op, [0, 1], [14, 0]);
  return (
    <div
      style={{
        opacity: op,
        transform: `translateY(${y}px)`,
        display: "inline-flex",
        flexDirection: "column",
        gap: 4,
        background: COLORS.bgPanel,
        border: `1px solid ${accent}`,
        borderLeft: `4px solid ${accent}`,
        borderRadius: 10,
        padding: "14px 22px",
        boxShadow: `0 12px 40px #00000070`,
      }}
    >
      <span
        style={{
          fontFamily: FONT.mono,
          fontSize: 26,
          fontWeight: 700,
          color: COLORS.text,
          letterSpacing: 0.5,
        }}
      >
        {label}
      </span>
      {sub && (
        <span
          style={{
            fontFamily: FONT.mono,
            fontSize: 17,
            color: COLORS.textMuted,
            letterSpacing: 1,
          }}
        >
          {sub}
        </span>
      )}
    </div>
  );
};
