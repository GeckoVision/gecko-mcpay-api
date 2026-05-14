import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export const EndCardScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const urlOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 });
  const urlScale = interpolate(urlOpacity, [0, 1], [0.98, 1]);

  const installOpacity = spring({ frame: frame - 24, fps, config: { damping: 200 }, durationInFrames: 22 });
  const tagOpacity = spring({ frame: frame - 60, fps, config: { damping: 200 }, durationInFrames: 22 });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap: 36,
      }}
    >
      {/* Spotlight */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at center, rgba(34, 227, 166, 0.08) 0%, transparent 60%)",
        }}
      />

      <div
        style={{
          fontFamily: FONT.display,
          fontSize: 108,
          fontWeight: 700,
          color: COLORS.text,
          letterSpacing: -3,
          opacity: urlOpacity,
          transform: `scale(${urlScale})`,
        }}
      >
        app<span style={{ color: COLORS.mint }}>.</span>geckovision<span style={{ color: COLORS.mint }}>.</span>tech
      </div>

      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 28,
          color: COLORS.textMuted,
          background: COLORS.bgPanel,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: "16px 28px",
          opacity: installOpacity,
        }}
      >
        <span style={{ color: COLORS.mint }}>$</span> curl -fsSL app.geckovision.tech/install.sh | bash
      </div>

      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 22,
          color: COLORS.textDim,
          letterSpacing: 4,
          marginTop: 12,
          opacity: tagOpacity,
        }}
      >
        NO API KEYS · JUST A WALLET
      </div>
    </AbsoluteFill>
  );
};
