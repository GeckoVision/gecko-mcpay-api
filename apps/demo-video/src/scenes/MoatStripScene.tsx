import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

const STATS: Array<{ value: string; label: string; tone: string }> = [
  { value: "4,874", label: "CORPUS CHUNKS", tone: COLORS.text },
  { value: "7", label: "PANEL VOICES", tone: COLORS.mint },
  { value: "80", label: "MAINNET TX", tone: COLORS.purple },
  { value: "$0.17", label: "LIFETIME SPEND", tone: COLORS.cyan },
];

const QUOTE = "None of them sell the verdict.";
const SUBQUOTE =
  "Marketplaces would have to pick a side on every listing in their own catalog. The strategy oracle layer is structurally ours.";

export const MoatStripScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const fadeOut = interpolate(frame, [420, 450], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap: 80,
        padding: 80,
        opacity: fadeOut,
      }}
    >
      {/* Quote */}
      <div style={{ textAlign: "center", maxWidth: 1400 }}>
        <div
          style={{
            fontFamily: FONT.display,
            fontSize: 88,
            fontWeight: 600,
            color: COLORS.text,
            letterSpacing: -2,
            opacity: spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 }),
          }}
        >
          {QUOTE}
        </div>
        <div
          style={{
            marginTop: 28,
            fontFamily: FONT.display,
            fontSize: 26,
            color: COLORS.textMuted,
            lineHeight: 1.5,
            opacity: spring({ frame: frame - 30, fps, config: { damping: 200 }, durationInFrames: 22 }),
          }}
        >
          {SUBQUOTE}
        </div>
      </div>

      {/* Stat strip */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${STATS.length}, 1fr)`,
          gap: 24,
          width: 1500,
        }}
      >
        {STATS.map((s, i) => {
          const start = 90 + i * 22;
          const op = spring({ frame: frame - start, fps, config: { damping: 200 }, durationInFrames: 22 });
          const ty = interpolate(op, [0, 1], [12, 0]);
          return (
            <div
              key={s.label}
              style={{
                background: COLORS.bgPanel,
                border: `1px solid ${COLORS.border}`,
                borderRadius: 16,
                padding: "32px 28px",
                opacity: op,
                transform: `translateY(${ty}px)`,
                textAlign: "center",
              }}
            >
              <div
                style={{
                  fontFamily: FONT.display,
                  fontSize: 72,
                  fontWeight: 700,
                  color: s.tone,
                  letterSpacing: -2,
                }}
              >
                {s.value}
              </div>
              <div
                style={{
                  marginTop: 8,
                  fontFamily: FONT.mono,
                  fontSize: 14,
                  letterSpacing: 2,
                  color: COLORS.textDim,
                }}
              >
                {s.label}
              </div>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
