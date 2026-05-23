import { AbsoluteFill, interpolate } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Caret } from "./primitives";
import { BEATS } from "./timing";

// Beat 1 — Title [0–120 / 0:00–0:04]
// "Gecko — weekly build update" · subhead "intelligence + safety for money-agents"
export const BeatTitle: React.FC = () => {
  const titleOp = useFade(0, 20);
  const subOp = useFade(16, 22);
  const tail = useBeatTail(BEATS.title.dur, 14);
  const titleY = interpolate(titleOp, [0, 1], [14, 0]);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        paddingLeft: 160,
        opacity: tail,
      }}
    >
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 20,
          letterSpacing: 8,
          textTransform: "uppercase",
          color: COLORS.mint,
          opacity: titleOp,
          marginBottom: 28,
        }}
      >
        weekly build update
      </div>
      <div
        style={{
          fontFamily: FONT.display,
          fontSize: 96,
          fontWeight: 800,
          letterSpacing: -3,
          color: COLORS.text,
          opacity: titleOp,
          transform: `translateY(${titleY}px)`,
        }}
      >
        Gecko <span style={{ color: COLORS.textDim, fontWeight: 300 }}>—</span> weekly
        build update
        <Caret />
      </div>
      <div
        style={{
          fontFamily: FONT.mono,
          fontSize: 30,
          color: COLORS.textMuted,
          opacity: subOp,
          marginTop: 32,
          letterSpacing: 0.5,
        }}
      >
        intelligence + safety for money-agents
      </div>
    </AbsoluteFill>
  );
};
