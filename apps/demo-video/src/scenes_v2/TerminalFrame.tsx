import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

// Reusable terminal chrome (macOS dots + title) for V2 frames.
export const TerminalFrame: React.FC<{
  title?: string;
  children: React.ReactNode;
  width?: number;
  minHeight?: number;
}> = ({ title = "Claude Code · ~/Gecko/gecko-mcpay-api", children, width = 1620, minHeight = 880 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const winOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 18 });
  const winY = interpolate(winOpacity, [0, 1], [16, 0]);

  // Floating drift backdrop
  const driftX = Math.sin(frame / 90) * 8;
  const driftY = Math.cos(frame / 110) * 8;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: COLORS.bg,
      }}
    >
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
      <div
        style={{
          width,
          minHeight,
          background: COLORS.bgPanel,
          borderRadius: 18,
          border: `1px solid ${COLORS.border}`,
          overflow: "hidden",
          opacity: winOpacity,
          transform: `translateY(${winY}px)`,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
          display: "flex",
          flexDirection: "column",
        }}
      >
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
        <div
          style={{
            padding: "32px 44px 44px",
            fontFamily: FONT.mono,
            fontSize: 18,
            lineHeight: 1.55,
            color: COLORS.text,
            flex: 1,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
};

// Type-on helper. Returns substring of `text` revealed at current frame.
export const useTypeOn = (text: string, startFrame: number, charsPerFrame = 2.8): {
  shown: string;
  done: boolean;
  caretVisible: boolean;
} => {
  const frame = useCurrentFrame();
  const charsShown = Math.max(
    0,
    Math.min(text.length, Math.floor((frame - startFrame) * charsPerFrame))
  );
  return {
    shown: text.slice(0, charsShown),
    done: charsShown >= text.length,
    caretVisible: Math.floor(frame / 8) % 2 === 0,
  };
};

export const Prompt: React.FC<{ text: string; startFrame?: number; speed?: number }> = ({
  text,
  startFrame = 8,
  speed = 3.0,
}) => {
  const { shown, done, caretVisible } = useTypeOn(text, startFrame, speed);
  return (
    <div style={{ marginBottom: 22 }}>
      <span style={{ color: COLORS.accent, marginRight: 10 }}>❯</span>
      <span>{shown}</span>
      {!done && (
        <span
          style={{
            display: "inline-block",
            width: 10,
            height: 20,
            marginLeft: 2,
            background: caretVisible ? COLORS.text : "transparent",
            verticalAlign: "middle",
          }}
        />
      )}
    </div>
  );
};
