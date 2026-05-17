import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

const PROMPT =
  "Use the gecko-trade-agent skill to deploy my strategy at ~/specs/example-kamino-dca.json in advisor mode.";

const INSPECT_LINES = [
  { c: COLORS.mint, t: "✓ Deployed. Background process is foreground-tick-driven." },
  { c: COLORS.textDim, t: "" },
  { c: COLORS.textMuted, t: "Command run" },
  { c: COLORS.text, t: "  uv run bb trade-agent up --spec ~/specs/example-kamino-dca.json" },
  { c: COLORS.textDim, t: "" },
  { c: COLORS.textMuted, t: "State" },
  {
    c: COLORS.text,
    t: "  agent_1a504l5b3f9f — status=",
    suffix: { v: "running", c: COLORS.mint },
    rest: ", mode=",
    suffix2: { v: "advisor", c: COLORS.purple },
  },
  { c: COLORS.text, t: "  Open positions: 0 (advisor mode — journals candidates only)" },
  { c: COLORS.text, t: "  Journal: agent_started at 2026-05-12T03:06:44 UTC" },
  { c: COLORS.textDim, t: "" },
  { c: COLORS.textMuted, t: "Steady-state cost ≈ $1.50/day · cache-then-charge" },
];

export const AgentDeployScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const winOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });

  // Type-on prompt
  const charsShown = Math.max(0, Math.min(PROMPT.length, Math.floor((frame - 12) * 2.6)));
  const typedText = PROMPT.slice(0, charsShown);

  // Output reveal starts at frame 130 (after prompt is fully typed)
  const outputStart = 130;

  const fadeOut = interpolate(frame, [570, 600], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

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
          width: 1500,
          background: COLORS.bgPanel,
          borderRadius: 18,
          border: `1px solid ${COLORS.border}`,
          overflow: "hidden",
          opacity: winOpacity,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
        }}
      >
        <TitleBar />
        <div
          style={{
            padding: "36px 44px 44px",
            fontFamily: FONT.mono,
            fontSize: 22,
            lineHeight: 1.45,
            color: COLORS.text,
            minHeight: 720,
          }}
        >
          <div style={{ color: COLORS.mint, marginBottom: 8 }}>❯ {typedText}</div>

          {/* Output */}
          {INSPECT_LINES.map((line, i) => {
            const lineStart = outputStart + i * 22;
            const op = spring({
              frame: frame - lineStart,
              fps,
              config: { damping: 200 },
              durationInFrames: 12,
            });
            return (
              <div key={i} style={{ color: line.c, opacity: op, marginTop: i === 0 ? 28 : 4 }}>
                {line.t}
                {line.suffix && <span style={{ color: line.suffix.c }}>{line.suffix.v}</span>}
                {line.rest}
                {line.suffix2 && <span style={{ color: line.suffix2.c }}>{line.suffix2.v}</span>}
              </div>
            );
          })}
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
    <div style={{ width: 12, height: 12, borderRadius: 6, background: "#FF5F57" }} />
    <div style={{ width: 12, height: 12, borderRadius: 6, background: "#FEBC2E" }} />
    <div style={{ width: 12, height: 12, borderRadius: 6, background: "#28C840" }} />
    <div
      style={{
        flex: 1,
        textAlign: "center",
        color: COLORS.textMuted,
        fontFamily: FONT.mono,
        fontSize: 14,
      }}
    >
      Claude Code · gecko-trade-agent · advisor mode
    </div>
  </div>
);
