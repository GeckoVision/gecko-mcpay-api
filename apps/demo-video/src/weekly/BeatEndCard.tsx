import { AbsoluteFill, interpolate } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, Caret } from "./primitives";

// Beat 7 — End card [1620–1800 / 0:54–1:00]
// "Your smart, honest agent — one you can trust with your money."
// small: "app.geckovision.tech"
export const BeatEndCard: React.FC = () => {
  const lineOp = useFade(8, 26);
  const urlOp = useFade(50, 22);
  const lineScale = interpolate(lineOp, [0, 1], [0.98, 1]);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          opacity: lineOp,
          transform: `scale(${lineScale})`,
          fontFamily: FONT.display,
          fontSize: 60,
          fontWeight: 800,
          letterSpacing: -1.5,
          color: COLORS.text,
          textAlign: "center",
          maxWidth: 1400,
          lineHeight: 1.25,
        }}
      >
        Your smart, honest agent —
        <br />
        one you can <span style={{ color: COLORS.mint }}>trust with your money.</span>
      </div>

      <div
        style={{
          opacity: urlOp,
          marginTop: 56,
          fontFamily: FONT.mono,
          fontSize: 28,
          color: COLORS.cyan,
          letterSpacing: 1,
        }}
      >
        app.geckovision.tech <Caret />
      </div>
    </AbsoluteFill>
  );
};
