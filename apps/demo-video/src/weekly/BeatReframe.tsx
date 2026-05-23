import { AbsoluteFill, interpolate } from "remotion";
import { COLORS } from "../theme";
import { useFade, useBeatTail, Eyebrow, Caption } from "./primitives";
import { BEATS } from "./timing";

// Beat 4 — The reframe [750–990 / 0:25–0:33]
// "Because we were never a trading bot." → "We're the brake, not the gas."
export const BeatReframe: React.FC = () => {
  const eyebrowOp = useFade(0, 16);
  const line1Op = useFade(12, 22);
  const line2Op = useFade(96, 24);
  const tail = useBeatTail(BEATS.reframe.dur, 14);
  const line2Y = interpolate(line2Op, [0, 1], [16, 0]);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        padding: "0 160px",
        opacity: tail,
      }}
    >
      <div style={{ opacity: eyebrowOp, marginBottom: 30 }}>
        <Eyebrow color={COLORS.textMuted}>the reframe</Eyebrow>
      </div>

      <div style={{ opacity: line1Op }}>
        <Caption size={56} color={COLORS.textMuted} weight={500}>
          Because we were never a trading bot.
        </Caption>
      </div>

      <div style={{ opacity: line2Op, transform: `translateY(${line2Y}px)`, marginTop: 36 }}>
        <Caption size={84} weight={800}>
          We're the <span style={{ color: COLORS.mint }}>brake</span>,
          <br />
          not the gas.
        </Caption>
      </div>
    </AbsoluteFill>
  );
};
