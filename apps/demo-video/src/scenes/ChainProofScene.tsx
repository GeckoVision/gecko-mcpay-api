import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

const TX = "4FPSxDGJQykp3j5cbnkGjAd8DVebsHBmazLQNCfEFZ3okKrgWCQi81ujr7aJS8MEbHUDXPEqn7EMAVBdAxwUyWoY";

export const ChainProofScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 });
  const cardY = interpolate(cardOpacity, [0, 1], [16, 0]);

  const rowOpacity = (start: number) =>
    spring({ frame: frame - start, fps, config: { damping: 200 }, durationInFrames: 18 });

  // Confirmed checkmark pulse
  const checkScale = spring({ frame: frame - 35, fps, config: { damping: 8, stiffness: 120 }, durationInFrames: 30 });

  const fadeOut = interpolate(frame, [270, 300], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
      }}
    >
      <div
        style={{
          width: 1280,
          background: COLORS.bgPanel,
          borderRadius: 20,
          border: `1px solid ${COLORS.border}`,
          padding: "40px 48px 48px",
          opacity: cardOpacity,
          transform: `translateY(${cardY}px)`,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
          fontFamily: FONT.display,
        }}
      >
        {/* Solscan-style header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 28,
            paddingBottom: 20,
            borderBottom: `1px solid ${COLORS.border}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: `linear-gradient(135deg, ${COLORS.purple}, ${COLORS.mint})`,
              }}
            />
            <div style={{ fontFamily: FONT.mono, color: COLORS.textMuted, fontSize: 18 }}>
              solscan.io / tx
            </div>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "8px 16px",
              background: "rgba(34, 227, 166, 0.12)",
              border: `1px solid ${COLORS.mint}55`,
              borderRadius: 999,
              color: COLORS.mint,
              fontFamily: FONT.mono,
              fontSize: 16,
              transform: `scale(${checkScale})`,
            }}
          >
            ✓ Confirmed
          </div>
        </div>

        {/* Signature */}
        <div style={{ opacity: rowOpacity(20), marginBottom: 28 }}>
          <Label>SIGNATURE</Label>
          <div
            style={{
              fontFamily: FONT.mono,
              fontSize: 22,
              color: COLORS.text,
              wordBreak: "break-all",
              marginTop: 6,
            }}
          >
            {TX.slice(0, 22)}<span style={{ color: COLORS.textMuted }}>…</span>{TX.slice(-22)}
          </div>
        </div>

        {/* Stats grid */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 16,
          }}
        >
          <Cell label="AMOUNT" value="$0.25" tone={COLORS.mint} delayed={rowOpacity(55)} />
          <Cell label="CHAIN" value="Solana" tone={COLORS.purple} delayed={rowOpacity(75)} />
          <Cell label="CONFIRMATION" value="1.6s" tone={COLORS.mint} delayed={rowOpacity(95)} />
          <Cell label="FEE" value="0.000005 SOL" tone={COLORS.text} delayed={rowOpacity(115)} />
        </div>

        <div
          style={{
            marginTop: 36,
            fontFamily: FONT.mono,
            color: COLORS.textDim,
            fontSize: 16,
            opacity: rowOpacity(160),
          }}
        >
          Real x402 settlement · No API key · No signup · Verify on Solscan
        </div>
      </div>
    </AbsoluteFill>
  );
};

const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontFamily: FONT.mono, fontSize: 12, letterSpacing: 2, color: COLORS.textDim }}>
    {children}
  </div>
);

const Cell: React.FC<{ label: string; value: string; tone: string; delayed: number }> = ({
  label,
  value,
  tone,
  delayed,
}) => (
  <div
    style={{
      background: COLORS.bgRaised,
      border: `1px solid ${COLORS.border}`,
      borderRadius: 12,
      padding: "16px 18px",
      opacity: delayed,
    }}
  >
    <Label>{label}</Label>
    <div style={{ marginTop: 8, fontSize: 26, fontWeight: 600, color: tone, fontFamily: FONT.display }}>
      {value}
    </div>
  </div>
);
