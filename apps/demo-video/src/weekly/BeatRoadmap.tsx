import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Eyebrow } from "./primitives";
import { BEATS } from "./timing";

// Beat 6 — Architecture + roadmap [1350–1620 / 0:45–0:54]
// Flow left→right: coach → ORACLE → execution (highlight ORACLE).
// Second line fades in: "paper → local → hosted · non-custodial · your keys, your money"

const NODES = [
  { label: "coach", hero: false },
  { label: "ORACLE", hero: true },
  { label: "execution", hero: false },
];

export const BeatRoadmap: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = useFade(0, 16);
  const line2Op = useFade(150, 24);
  const tail = useBeatTail(BEATS.roadmap.dur, 14);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        opacity: tail,
      }}
    >
      <div style={{ opacity: eyebrowOp, marginBottom: 56 }}>
        <Eyebrow color={COLORS.textMuted}>architecture</Eyebrow>
      </div>

      {/* Flow: coach → ORACLE → execution */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {NODES.map((n, i) => {
          const nodeOp = useFade(20 + i * 26, 18);
          const arrowOp = useFade(20 + i * 26 + 14, 16);
          const nodeY = interpolate(nodeOp, [0, 1], [10, 0]);
          return (
            <div key={n.label} style={{ display: "flex", alignItems: "center" }}>
              <div
                style={{
                  opacity: nodeOp,
                  transform: `translateY(${nodeY}px)`,
                  fontFamily: FONT.mono,
                  fontSize: n.hero ? 56 : 38,
                  fontWeight: n.hero ? 800 : 500,
                  letterSpacing: n.hero ? 3 : 1,
                  color: n.hero ? COLORS.mint : COLORS.textMuted,
                  background: n.hero ? COLORS.mintDim : COLORS.bgPanel,
                  border: `1px solid ${n.hero ? COLORS.mint : COLORS.border}`,
                  borderRadius: 14,
                  padding: n.hero ? "26px 46px" : "20px 34px",
                  boxShadow: n.hero ? `0 0 40px ${COLORS.mint}30` : "none",
                }}
              >
                {n.label}
              </div>
              {i < NODES.length - 1 && (
                <span
                  style={{
                    opacity: arrowOp,
                    fontFamily: FONT.mono,
                    fontSize: 44,
                    color: COLORS.textDim,
                    margin: "0 22px",
                  }}
                >
                  →
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div
        style={{
          opacity: line2Op,
          marginTop: 64,
          fontFamily: FONT.mono,
          fontSize: 28,
          color: COLORS.textMuted,
          letterSpacing: 1,
          textAlign: "center",
        }}
      >
        <span style={{ color: COLORS.text }}>paper → local → hosted</span>
        <span style={{ color: COLORS.textDim }}> · </span>
        non-custodial
        <span style={{ color: COLORS.textDim }}> · </span>
        <span style={{ color: COLORS.mint }}>your keys, your money</span>
      </div>
    </AbsoluteFill>
  );
};
