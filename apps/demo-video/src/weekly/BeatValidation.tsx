import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Eyebrow, Caption } from "./primitives";
import { BEATS } from "./timing";

// Beat 5 — The validation (the win) [990–1350 / 0:33–0:45]
// Headline: "We measured the product: the Gecko Oracle."
// Key line: "When it says ACT, those trades beat the ones it says DEFER."
// Stat chip: "+1.1% gating delta · even in chop" + caveat "early signal · N=30 · replicating"
// Motif: compact verdict-envelope card + ACT > DEFER bars. Caveat must be visible.

export const BeatValidation: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = useFade(0, 16);
  const headOp = useFade(10, 22);
  const cardOp = useFade(48, 20);
  const keyLineOp = useFade(150, 22);
  const chipOp = useFade(210, 22);
  const caveatOp = useFade(238, 22);
  const tail = useBeatTail(BEATS.validation.dur, 14);

  // ACT vs DEFER bars grow; ACT clearly beats DEFER.
  const grow = interpolate(frame, [70, 150], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        padding: "0 140px",
        opacity: tail,
      }}
    >
      <div style={{ opacity: eyebrowOp, marginBottom: 22 }}>
        <Eyebrow color={COLORS.mint}>the validation</Eyebrow>
      </div>

      <div style={{ opacity: headOp }}>
        <Caption size={52} weight={700}>
          We measured the product:{" "}
          <span style={{ color: COLORS.mint }}>the Gecko Oracle.</span>
        </Caption>
      </div>

      <div style={{ display: "flex", gap: 48, marginTop: 40, alignItems: "stretch" }}>
        {/* Verdict-envelope card */}
        <div
          style={{
            opacity: cardOp,
            background: COLORS.bgPanel,
            border: `1px solid ${COLORS.border}`,
            borderRadius: 14,
            padding: "26px 32px",
            minWidth: 520,
            fontFamily: FONT.mono,
          }}
        >
          <div
            style={{
              fontSize: 13,
              letterSpacing: 3,
              textTransform: "uppercase",
              color: COLORS.textMuted,
              marginBottom: 18,
            }}
          >
            verdict envelope
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
            <span
              style={{
                fontSize: 13,
                letterSpacing: 2,
                textTransform: "uppercase",
                color: COLORS.textMuted,
              }}
            >
              verdict
            </span>
            <span
              style={{
                fontSize: 44,
                fontWeight: 800,
                letterSpacing: 4,
                color: COLORS.mint,
              }}
            >
              ACT
            </span>
          </div>
          <div
            style={{
              borderTop: `1px solid ${COLORS.border}`,
              marginTop: 18,
              paddingTop: 16,
              fontSize: 18,
              lineHeight: 1.9,
            }}
          >
            <div>
              <span style={{ color: COLORS.textDim }}>dissent: </span>
              <span style={{ color: COLORS.magenta }}>survives</span>
            </div>
            <div>
              <span style={{ color: COLORS.textDim }}>citations: </span>
              <span style={{ color: COLORS.cyan }}>investor-canon</span>
            </div>
          </div>
        </div>

        {/* ACT > DEFER bars */}
        <div
          style={{
            opacity: cardOp,
            flex: 1,
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            gap: 26,
          }}
        >
          <GatingBar
            label="ACT trades"
            width={420 * grow}
            color={COLORS.mint}
            value="outperform"
          />
          <GatingBar
            label="DEFER trades"
            width={210 * grow}
            color={COLORS.verdictDefer}
            value="lag"
          />
        </div>
      </div>

      <div style={{ opacity: keyLineOp, marginTop: 40 }}>
        <Caption size={36} weight={600} mono>
          When it says <span style={{ color: COLORS.mint }}>ACT</span>, those trades
          beat the ones it says{" "}
          <span style={{ color: COLORS.verdictDefer }}>DEFER</span>.
        </Caption>
      </div>

      {/* Stat chip + visible caveat */}
      <div style={{ display: "flex", alignItems: "center", gap: 22, marginTop: 28 }}>
        <div
          style={{
            opacity: chipOp,
            display: "inline-flex",
            alignItems: "center",
            gap: 12,
            background: COLORS.mintDim,
            border: `1px solid ${COLORS.mint}`,
            borderRadius: 999,
            padding: "12px 24px",
            fontFamily: FONT.mono,
            fontSize: 26,
            fontWeight: 700,
            color: COLORS.mint,
          }}
        >
          +1.1% gating delta · even in chop
        </div>
        <div
          style={{
            opacity: caveatOp,
            fontFamily: FONT.mono,
            fontSize: 18,
            color: COLORS.textDim,
            letterSpacing: 1,
          }}
        >
          early signal · N=30 · replicating
        </div>
      </div>
    </AbsoluteFill>
  );
};

const GatingBar: React.FC<{
  label: string;
  width: number;
  color: string;
  value: string;
}> = ({ label, width, color, value }) => (
  <div>
    <div
      style={{
        fontFamily: FONT.mono,
        fontSize: 16,
        color: COLORS.textMuted,
        marginBottom: 8,
      }}
    >
      {label}
    </div>
    <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
      <div
        style={{
          height: 28,
          width: Math.max(width, 2),
          background: color,
          opacity: 0.85,
          borderRadius: 4,
          boxShadow: `0 0 16px ${color}40`,
        }}
      />
      <span style={{ fontFamily: FONT.mono, fontSize: 16, color }}>{value}</span>
    </div>
  </div>
);
