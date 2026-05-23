import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Eyebrow, Caption } from "./primitives";
import { BEATS } from "./timing";

// Beat 3 — The honest reckoning [300–540 / 0:10–0:18]
// "We measured it. Fees ate the edge."
// REAL numbers: gross edge ~+0.17% vs round-trip fee ~0.75% (fee ~4× the edge).
// The bars are scaled to the true ratio — fees dwarf the edge.

const EDGE = 0.17; // gross edge, %
const FEE = 0.75; // round-trip fee + slippage, %
const MAX_BAR = 720; // px at the larger value
const RATIO = Math.round(FEE / EDGE); // ~4

export const BeatReckoning: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = useFade(0, 16);
  const headOp = useFade(10, 22);
  const barsOp = useFade(40, 20);
  const revealOp = useFade(140, 24);
  const tail = useBeatTail(BEATS.reckoning.dur, 14);

  const grow = interpolate(frame, [50, 120], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  // Bars share a scale so the fee:edge ratio is honest on screen.
  const edgeW = (EDGE / FEE) * MAX_BAR * grow;
  const feeW = MAX_BAR * grow;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        padding: "0 160px",
        opacity: tail,
      }}
    >
      <div style={{ opacity: eyebrowOp, marginBottom: 26 }}>
        <Eyebrow color={COLORS.textMuted}>the reckoning</Eyebrow>
      </div>

      <div style={{ opacity: headOp }}>
        <Caption size={60} weight={700}>
          We measured it.{" "}
          <span style={{ color: COLORS.magenta }}>Fees ate the edge.</span>
        </Caption>
      </div>

      {/* Honest fee vs edge bars — scaled to the real ~4× ratio */}
      <div style={{ marginTop: 56, opacity: barsOp, maxWidth: 1100 }}>
        <BarRow
          label="gross edge"
          width={edgeW}
          color={COLORS.mint}
          value="~+0.17%"
        />
        <div style={{ height: 22 }} />
        <BarRow
          label="round-trip fee"
          width={feeW}
          color={COLORS.magenta}
          value="~0.75%"
        />
        <div
          style={{
            fontFamily: FONT.mono,
            fontSize: 18,
            color: COLORS.textDim,
            marginTop: 24,
          }}
        >
          fees were ~{RATIO}× the edge · breakout strategy · chop regime
        </div>
      </div>

      <div style={{ opacity: revealOp, marginTop: 48 }}>
        <Caption size={42} weight={700} color={COLORS.text}>
          So we stopped chasing returns —{" "}
          <span style={{ color: COLORS.mint }}>and built the brake.</span>
        </Caption>
      </div>
    </AbsoluteFill>
  );
};

const BarRow: React.FC<{
  label: string;
  width: number;
  color: string;
  value: string;
}> = ({ label, width, color, value }) => (
  <div style={{ display: "flex", alignItems: "center", gap: 22 }}>
    <div
      style={{
        width: 220,
        fontFamily: FONT.mono,
        fontSize: 20,
        color: COLORS.textMuted,
        textAlign: "right",
      }}
    >
      {label}
    </div>
    <div
      style={{
        height: 38,
        width: Math.max(width, 2),
        background: color,
        opacity: 0.85,
        borderRadius: 4,
        boxShadow: `0 0 18px ${color}40`,
      }}
    />
    <div
      style={{
        fontFamily: FONT.mono,
        fontSize: 24,
        fontWeight: 700,
        color,
      }}
    >
      {value}
    </div>
  </div>
);
