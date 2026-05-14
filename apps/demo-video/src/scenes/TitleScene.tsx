import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export const TitleScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 25 });
  const titleY = interpolate(titleOpacity, [0, 1], [16, 0]);

  const subOpacity = spring({
    frame: frame - 18,
    fps,
    config: { damping: 200 },
    durationInFrames: 25,
  });

  const fadeOut = interpolate(frame, [120, 150], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          fontFamily: FONT.display,
          color: COLORS.text,
          fontSize: 72,
          fontWeight: 600,
          letterSpacing: -1.5,
          textAlign: "center",
          opacity: titleOpacity,
          transform: `translateY(${titleY}px)`,
          maxWidth: 1400,
        }}
      >
        Gecko — strategy oracle for autonomous trading agents
      </div>
      <div
        style={{
          marginTop: 32,
          fontFamily: FONT.mono,
          color: COLORS.textMuted,
          fontSize: 22,
          letterSpacing: 1,
          opacity: subOpacity,
        }}
      >
        by ernani
      </div>

      {/* fine grid */}
      <Grid />
    </AbsoluteFill>
  );
};

const Grid: React.FC = () => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      pointerEvents: "none",
      backgroundImage:
        "radial-gradient(circle at center, rgba(255,255,255,0.03) 1px, transparent 1px)",
      backgroundSize: "40px 40px",
      maskImage: "radial-gradient(ellipse at center, black 40%, transparent 80%)",
    }}
  />
);
