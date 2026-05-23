import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Eyebrow, Caption } from "./primitives";
import { BEATS } from "./timing";

// Beat 3 — The honest reckoning [390–750 / 0:13–0:25]
// Headline: "Then we measured it. Five experiments."
// Reveal: "Verdict: our own strategy had no edge. Fees ate it."
// Motif: a tiny fee table / a bar where fee > edge. Show the loss honestly.

export const BeatReckoning: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = useFade(0, 16);
  const headOp = useFade(10, 22);
  const barsOp = useFade(60, 20);
  const revealOp = useFade(180, 24);
  const tail = useBeatTail(BEATS.reckoning.dur, 14);

  // Bars grow in. Edge is small + mint; fees are larger + muted red — fee > edge.
  const grow = interpolate(frame, [70, 150], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const edgeW = 150 * grow; // gross edge, small
  const feeW = 230 * grow; // fees, larger — eats the edge

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
          Then we measured it.{" "}
          <span style={{ color: COLORS.mint }}>Five experiments.</span>
        </Caption>
      </div>

      {/* Honest fee vs edge bars */}
      <div style={{ marginTop: 52, opacity: barsOp, maxWidth: 760 }}>
        <BarRow
          label="gross edge"
          width={edgeW}
          color={COLORS.mint}
          value="+0.3%"
        />
        <div style={{ height: 18 }} />
        <BarRow
          label="fees + slippage"
          width={feeW}
          color={COLORS.magenta}
          value="−0.5%"
        />
        <div
          style={{
            fontFamily: FONT.mono,
            fontSize: 16,
            color: COLORS.textDim,
            marginTop: 20,
          }}
        >
          5 experiments · breakout strategy · chop regime
        </div>
      </div>

      <div style={{ opacity: revealOp, marginTop: 48 }}>
        <Caption size={42} weight={700} color={COLORS.text}>
          Verdict:{" "}
          <span style={{ color: COLORS.magenta }}>
            our own strategy had no edge.
          </span>{" "}
          Fees ate it.
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
        width: 200,
        fontFamily: FONT.mono,
        fontSize: 18,
        color: COLORS.textMuted,
        textAlign: "right",
      }}
    >
      {label}
    </div>
    <div
      style={{
        height: 34,
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
        fontSize: 22,
        fontWeight: 700,
        color,
      }}
    >
      {value}
    </div>
  </div>
);
