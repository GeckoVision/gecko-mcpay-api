import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

const PROMPT = "Should I deposit USDC into the Kamino USDC reserve right now?";

export const HookScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const winOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });
  const winY = interpolate(winOpacity, [0, 1], [24, 0]);

  // Type-on the prompt starting frame 30, ~3 chars/frame = ~80 frames
  const charsShown = Math.max(0, Math.min(PROMPT.length, Math.floor((frame - 30) * 2.4)));
  const typedText = PROMPT.slice(0, charsShown);

  // Caret blink
  const caretVisible = Math.floor(frame / 8) % 2 === 0;

  // Fade out at the end
  const fadeOut = interpolate(frame, [270, 300], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      {/* Claude Code window mock */}
      <div
        style={{
          width: 1400,
          backgroundColor: COLORS.bgPanel,
          borderRadius: 18,
          border: `1px solid ${COLORS.border}`,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
          opacity: winOpacity,
          transform: `translateY(${winY}px)`,
          overflow: "hidden",
        }}
      >
        <TitleBar />
        <div
          style={{
            padding: "44px 56px 56px",
            fontFamily: FONT.mono,
            fontSize: 28,
            lineHeight: 1.45,
            color: COLORS.text,
          }}
        >
          <div style={{ color: COLORS.textMuted, marginBottom: 14 }}>
            <span style={{ color: COLORS.mint }}>$</span> claude
          </div>
          <div style={{ color: COLORS.textDim, marginBottom: 28, fontSize: 22 }}>
            Claude Code v2.1.139 · Opus 4.7 (1M context)
          </div>
          <div>
            <span style={{ color: COLORS.mint }}>❯ </span>
            <span>{typedText}</span>
            <span
              style={{
                display: "inline-block",
                width: 12,
                height: 28,
                marginLeft: 2,
                background: caretVisible ? COLORS.text : "transparent",
                verticalAlign: "middle",
              }}
            />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const TitleBar: React.FC = () => (
  <div
    style={{
      height: 44,
      background: COLORS.bgRaised,
      borderBottom: `1px solid ${COLORS.border}`,
      display: "flex",
      alignItems: "center",
      padding: "0 18px",
      gap: 8,
    }}
  >
    <Dot color="#FF5F57" />
    <Dot color="#FEBC2E" />
    <Dot color="#28C840" />
    <div
      style={{
        flex: 1,
        textAlign: "center",
        color: COLORS.textMuted,
        fontFamily: FONT.mono,
        fontSize: 14,
      }}
    >
      Claude Code · ~/Gecko/gecko-mcpay-api
    </div>
  </div>
);

const Dot: React.FC<{ color: string }> = ({ color }) => (
  <div style={{ width: 12, height: 12, borderRadius: 6, background: color }} />
);
