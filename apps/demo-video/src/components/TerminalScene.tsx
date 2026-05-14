import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export type TerminalLine = {
  // Visual style
  kind?: "user" | "action" | "subtle" | "body" | "blank" | "heading" | "code" | "result";
  // Content — either plain text, or an array of {text, color} spans
  text?: string;
  spans?: Array<{ text: string; color?: string; bold?: boolean }>;
  // Indentation level (each unit = 16px)
  indent?: number;
};

export type TerminalSceneProps = {
  title?: string;
  prompt: string;
  // Frame at which output starts revealing (after prompt finishes typing)
  outputStartFrame: number;
  lines: TerminalLine[];
  // Stagger between line reveals (frames)
  lineStagger?: number;
  // Optional fade-out frame range [start, end]
  fadeOut?: [number, number];
  // Type-on speed (chars/frame)
  typeSpeed?: number;
};

export const TerminalScene: React.FC<TerminalSceneProps> = ({
  title = "Claude Code · ~/Gecko/gecko-mcpay-api",
  prompt,
  outputStartFrame,
  lines,
  lineStagger = 8,
  fadeOut,
  typeSpeed = 3.2,
}) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // Window entrance
  const winOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });
  const winY = interpolate(winOpacity, [0, 1], [16, 0]);

  // Type-on prompt
  const promptStartFrame = 8;
  const charsShown = Math.max(0, Math.min(prompt.length, Math.floor((frame - promptStartFrame) * typeSpeed)));
  const typedText = prompt.slice(0, charsShown);
  const isTyping = charsShown < prompt.length;
  const caretVisible = Math.floor(frame / 8) % 2 === 0;

  // Fade out
  const [foStart, foEnd] = fadeOut ?? [durationInFrames - 20, durationInFrames];
  const fadeOpacity = interpolate(frame, [foStart, foEnd], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOpacity,
      }}
    >
      {/* Subtle backdrop noise + grid */}
      <Backdrop />

      <div
        style={{
          width: 1620,
          maxHeight: 920,
          background: COLORS.bgPanel,
          borderRadius: 18,
          border: `1px solid ${COLORS.border}`,
          overflow: "hidden",
          opacity: winOpacity,
          transform: `translateY(${winY}px)`,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
        }}
      >
        <TitleBar title={title} />
        <div
          style={{
            padding: "32px 44px 44px",
            fontFamily: FONT.mono,
            fontSize: 20,
            lineHeight: 1.5,
            color: COLORS.text,
          }}
        >
          {/* Prompt */}
          <div style={{ marginBottom: 18 }}>
            <span style={{ color: COLORS.mint, marginRight: 8 }}>❯</span>
            <span>{typedText}</span>
            {isTyping && (
              <span
                style={{
                  display: "inline-block",
                  width: 10,
                  height: 22,
                  marginLeft: 2,
                  background: caretVisible ? COLORS.text : "transparent",
                  verticalAlign: "middle",
                }}
              />
            )}
          </div>

          {/* Output */}
          {lines.map((line, i) => {
            const lineStart = outputStartFrame + i * lineStagger;
            const op = spring({
              frame: frame - lineStart,
              fps,
              config: { damping: 200 },
              durationInFrames: 10,
            });
            return (
              <LineRow key={i} line={line} opacity={op} />
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const LineRow: React.FC<{ line: TerminalLine; opacity: number }> = ({ line, opacity }) => {
  const kind = line.kind ?? "body";
  const indent = (line.indent ?? 0) * 16;

  if (kind === "blank") {
    return <div style={{ height: 8, opacity }} />;
  }

  const containerStyle: React.CSSProperties = {
    opacity,
    paddingLeft: indent,
    marginTop: kind === "heading" ? 14 : 2,
    marginBottom: kind === "heading" ? 4 : 2,
    fontFamily: FONT.mono,
  };

  // Style by kind
  let color = COLORS.text;
  let weight: number | undefined = undefined;
  let prefix: React.ReactNode = null;

  if (kind === "action") {
    color = COLORS.text;
    prefix = <span style={{ color: COLORS.magenta, marginRight: 10 }}>●</span>;
  } else if (kind === "result") {
    color = COLORS.text;
    weight = 600;
    prefix = <span style={{ color: COLORS.mint, marginRight: 10 }}>●</span>;
  } else if (kind === "subtle") {
    color = COLORS.textDim;
  } else if (kind === "heading") {
    weight = 700;
    color = COLORS.text;
  } else if (kind === "code") {
    color = COLORS.cyan;
  }

  return (
    <div style={{ ...containerStyle, color, fontWeight: weight }}>
      {prefix}
      {line.spans
        ? line.spans.map((s, j) => (
            <span key={j} style={{ color: s.color ?? color, fontWeight: s.bold ? 700 : weight }}>
              {s.text}
            </span>
          ))
        : line.text}
    </div>
  );
};

const TitleBar: React.FC<{ title: string }> = ({ title }) => (
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
      {title}
    </div>
  </div>
);

const Backdrop: React.FC = () => {
  const frame = useCurrentFrame();
  // Slow floating drift
  const driftX = Math.sin(frame / 90) * 8;
  const driftY = Math.cos(frame / 110) * 8;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        backgroundImage:
          "radial-gradient(circle at center, rgba(255,255,255,0.025) 1px, transparent 1px)",
        backgroundSize: "44px 44px",
        backgroundPosition: `${driftX}px ${driftY}px`,
        maskImage: "radial-gradient(ellipse at center, black 30%, transparent 80%)",
      }}
    />
  );
};
