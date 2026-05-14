import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export const EndCardV2: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const urlOp = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 });
  const urlScale = interpolate(urlOp, [0, 1], [0.97, 1]);
  const installOp = spring({ frame: frame - 24, fps, config: { damping: 200 }, durationInFrames: 22 });
  const tagOp = spring({ frame: frame - 60, fps, config: { damping: 200 }, durationInFrames: 22 });

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
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: "radial-gradient(ellipse at center, rgba(34, 227, 166, 0.08) 0%, transparent 60%)",
        }}
      />
      <div
        style={{
          fontFamily: FONT.display,
          fontSize: 130,
          fontWeight: 800,
          color: COLORS.text,
          letterSpacing: -4,
          opacity: urlOp,
          transform: `scale(${urlScale})`,
        }}
      >
        app<span style={{ color: COLORS.mint }}>.</span>geckovision<span style={{ color: COLORS.mint }}>.</span>tech
      </div>
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 30,
          color: COLORS.textMuted,
          background: COLORS.bgPanel,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 12,
          padding: "18px 32px",
          opacity: installOp,
        }}
      >
        <span style={{ color: COLORS.mint }}>$</span> curl -fsSL app.geckovision.tech/install.sh | bash
      </div>
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 22,
          color: COLORS.textDim,
          letterSpacing: 5,
          marginTop: 14,
          opacity: tagOp,
        }}
      >
        NO API KEYS · JUST A WALLET
      </div>
    </AbsoluteFill>
  );
};
