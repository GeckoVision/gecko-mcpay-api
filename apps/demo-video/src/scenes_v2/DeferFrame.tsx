import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";
import { Prompt, TerminalFrame } from "./TerminalFrame";

const QUESTION = "What's the right MEV tip floor for a 2 SOL Jupiter swap right now?";

export const DeferFrame: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // After typing (~ frame 90), panel collapses fast
  const panelStart = 110;
  const verdictStart = 220;
  const honestLineStart = 360;
  const blockerStart = 470;

  const panelOp = spring({ frame: frame - panelStart, fps, config: { damping: 200 }, durationInFrames: 14 });
  const verdictOp = spring({ frame: frame - verdictStart, fps, config: { damping: 200 }, durationInFrames: 18 });
  const honestOp = spring({ frame: frame - honestLineStart, fps, config: { damping: 200 }, durationInFrames: 18 });
  const blockerOp = spring({ frame: frame - blockerStart, fps, config: { damping: 200 }, durationInFrames: 18 });

  const conf = interpolate(frame, [verdictStart, verdictStart + 50], [0, 0.4], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TerminalFrame>
        <Prompt text={QUESTION} startFrame={6} speed={2.8} />

        {/* Quick panel ping */}
        <div style={{ opacity: panelOp, marginTop: 14, color: COLORS.textMuted }}>
          <span style={{ color: COLORS.mint, marginRight: 10 }}>●</span>
          Calling 7 voices… <span style={{ color: COLORS.textDim }}>·  responses in 3.1s</span>
        </div>

        <div style={{ opacity: panelOp, marginTop: 6, color: COLORS.textDim, fontSize: 15 }}>
          <span style={{ marginLeft: 22 }}>4 of 7 abstain · corpus too thin for directional call</span>
        </div>

        {/* Verdict */}
        <div
          style={{
            marginTop: 28,
            borderTop: `1px solid ${COLORS.border}`,
            paddingTop: 20,
            display: "flex",
            alignItems: "baseline",
            gap: 22,
            opacity: verdictOp,
          }}
        >
          <span style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            verdict
          </span>
          <span
            style={{
              color: COLORS.amber,
              fontSize: 38,
              fontWeight: 700,
              letterSpacing: 4,
              fontFamily: FONT.display,
              textTransform: "uppercase",
            }}
          >
            DEFER
          </span>
          <span style={{ marginLeft: "auto", color: COLORS.textMuted, fontFamily: FONT.mono, fontSize: 18 }}>
            conf <span style={{ color: COLORS.text }}>{conf.toFixed(2)}</span>
          </span>
        </div>

        <div style={{ opacity: verdictOp, marginTop: 10 }}>
          <div
            style={{
              height: 5,
              width: "100%",
              background: COLORS.bgRaised,
              borderRadius: 2,
              overflow: "hidden",
              border: `1px solid ${COLORS.border}`,
            }}
          >
            <div style={{ height: "100%", width: `${conf * 100}%`, background: COLORS.amber, opacity: 0.55 }} />
          </div>
        </div>

        {/* Honest defer message */}
        <div
          style={{
            marginTop: 48,
            padding: "26px 28px",
            background: COLORS.bgRaised,
            border: `1px solid ${COLORS.border}`,
            borderLeft: `3px solid ${COLORS.amber}`,
            borderRadius: 8,
            opacity: honestOp,
          }}
        >
          <div style={{ color: COLORS.textMuted, fontSize: 12, letterSpacing: 2, textTransform: "uppercase" }}>
            honest defer
          </div>
          <div
            style={{
              color: COLORS.text,
              fontSize: 30,
              fontFamily: FONT.display,
              fontWeight: 600,
              marginTop: 10,
              letterSpacing: -0.5,
            }}
          >
            Corpus too thin<span style={{ color: COLORS.amber }}>.</span> I won't pretend to know<span style={{ color: COLORS.amber }}>.</span>
          </div>
          <div style={{ color: COLORS.textMuted, fontSize: 16, marginTop: 10 }}>
            0 citations from market_data · 0 from paysh_live · 0 from canon. Defer is the only honest call.
          </div>
        </div>

        {/* Blocker */}
        <div style={{ opacity: blockerOp, marginTop: 22 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            blocker
          </div>
          <div style={{ color: COLORS.text, marginTop: 4, fontSize: 16 }}>
            <span style={{ color: COLORS.textDim, marginRight: 8 }}>·</span>
            Connect a live Jito tip stream or paysh fee feed; re-run.
          </div>
        </div>
      </TerminalFrame>
    </AbsoluteFill>
  );
};
