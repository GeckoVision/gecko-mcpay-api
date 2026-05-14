import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Fade in 0-20, hold, fade out last 25
  const fadeIn = interpolate(frame, [0, 22], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [durationInFrames - 25, durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = Math.min(fadeIn, fadeOut);
  const lift = interpolate(fadeIn, [0, 1], [12, 0]);

  const taglineFade = interpolate(frame, [18, 40], [0, 1], { extrapolateRight: "clamp" });
  const taglineOpacity = Math.min(taglineFade, fadeOut);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap: 28,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at center, rgba(34, 227, 166, 0.06) 0%, transparent 65%)",
        }}
      />
      <div
        style={{
          fontFamily: FONT.display,
          fontSize: 220,
          fontWeight: 800,
          color: COLORS.text,
          letterSpacing: -10,
          opacity,
          transform: `translateY(${lift}px)`,
        }}
      >
        GECKO
      </div>
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 26,
          color: COLORS.textMuted,
          letterSpacing: 1,
          opacity: taglineOpacity,
        }}
      >
        Grounded crypto verdicts<span style={{ color: COLORS.mint }}>.</span> Or an honest defer<span style={{ color: COLORS.mint }}>.</span>
      </div>
    </AbsoluteFill>
  );
};
