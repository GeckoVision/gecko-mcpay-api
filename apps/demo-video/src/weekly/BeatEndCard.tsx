import { AbsoluteFill, interpolate } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, Caret } from "./primitives";

// Beat 7 — End card [1590–1800 / 0:53–1:00]
// "Your smart, honest agent — one you can trust with your money."
// CTA: waitlist — geckovision.tech/#waitlist · "join the waitlist · still validating"
export const BeatEndCard: React.FC = () => {
  const lineOp = useFade(8, 26);
  const ctaOp = useFade(50, 22);
  const subOp = useFade(72, 22);
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

      {/* Waitlist CTA */}
      <div
        style={{
          opacity: ctaOp,
          marginTop: 56,
          display: "inline-flex",
          alignItems: "center",
          gap: 14,
          background: COLORS.mintDim,
          border: `1px solid ${COLORS.mint}`,
          borderRadius: 999,
          padding: "16px 34px",
          fontFamily: FONT.mono,
          fontSize: 34,
          fontWeight: 700,
          color: COLORS.mint,
          letterSpacing: 0.5,
        }}
      >
        geckovision.tech/#waitlist <Caret />
      </div>

      <div
        style={{
          opacity: subOp,
          marginTop: 24,
          fontFamily: FONT.mono,
          fontSize: 22,
          color: COLORS.textDim,
          letterSpacing: 1,
        }}
      >
        join the waitlist · still validating
      </div>
    </AbsoluteFill>
  );
};
