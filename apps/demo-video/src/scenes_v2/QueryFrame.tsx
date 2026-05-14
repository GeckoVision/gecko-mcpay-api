import { interpolate, spring, useCurrentFrame, useVideoConfig, AbsoluteFill } from "remotion";
import { COLORS } from "../theme";
import { Prompt, TerminalFrame } from "./TerminalFrame";

const QUESTION =
  "Is the JLP-USDC vault on Kamino worth depositing right now?";

export const QueryFrame: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Typing finishes around frame 8 + 67/3 = ~30; show callout after.
  const calloutStart = 220;
  const calloutOp = spring({ frame: frame - calloutStart, fps, config: { damping: 200 }, durationInFrames: 16 });

  const pulseStart = 300;
  const pulseOp = spring({ frame: frame - pulseStart, fps, config: { damping: 200 }, durationInFrames: 14 });

  // pulsing dot
  const pulse = 0.55 + 0.45 * Math.sin((frame - pulseStart) / 5);

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TerminalFrame>
        <Prompt text={QUESTION} startFrame={10} speed={2.6} />

        <div style={{ opacity: calloutOp, marginTop: 12 }}>
          <span style={{ color: COLORS.mint, marginRight: 10 }}>●</span>
          <span style={{ color: COLORS.text }}>Calling </span>
          <span style={{ color: COLORS.cyan }}>gecko_trade_research</span>
          <span style={{ color: COLORS.textMuted }}>{"  ·  "}7-agent panel · investor canon · protocol-native</span>
        </div>

        <div style={{ opacity: pulseOp, marginTop: 18, color: COLORS.textMuted }}>
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: 5,
              background: COLORS.mint,
              marginRight: 12,
              opacity: pulse,
              boxShadow: `0 0 18px rgba(34, 227, 166, ${pulse * 0.7})`,
            }}
          />
          Calling 7 voices...
        </div>
      </TerminalFrame>
    </AbsoluteFill>
  );
};
