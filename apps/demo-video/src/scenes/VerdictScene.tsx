import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";

export const VerdictScene: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Card entrance
  const cardOpacity = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 });
  const cardScale = interpolate(cardOpacity, [0, 1], [0.97, 1]);

  // Per-row staggered reveal
  const rowFrames = [25, 55, 85, 115, 145, 175, 205];
  const rowOpacity = (start: number) =>
    spring({ frame: frame - start, fps, config: { damping: 200 }, durationInFrames: 20 });

  // Confidence bar fill
  const barFill = interpolate(frame, [100, 200], [0, 0.75], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Dissent highlight pulse
  const dissentPulse = 0.85 + 0.15 * Math.sin((frame - 200) / 8);

  const fadeOut = interpolate(frame, [570, 600], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        backgroundColor: COLORS.bg,
        justifyContent: "center",
        alignItems: "center",
        opacity: fadeOut,
        padding: 80,
      }}
    >
      <div
        style={{
          width: 1280,
          background: COLORS.bgPanel,
          border: `1px solid ${COLORS.border}`,
          borderRadius: 24,
          padding: "48px 56px 56px",
          opacity: cardOpacity,
          transform: `scale(${cardScale})`,
          boxShadow: "0 40px 120px rgba(0,0,0,0.6)",
          fontFamily: FONT.display,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 36,
            opacity: rowOpacity(rowFrames[0]),
          }}
        >
          <div>
            <div style={{ fontFamily: FONT.mono, color: COLORS.textDim, fontSize: 16, letterSpacing: 2 }}>
              TRADE PANEL VERDICT
            </div>
            <div style={{ color: COLORS.text, fontSize: 44, fontWeight: 600, marginTop: 8 }}>
              Kamino USDC Reserve
            </div>
          </div>
          <ActPill />
        </div>

        {/* Confidence */}
        <div style={{ opacity: rowOpacity(rowFrames[1]), marginBottom: 36 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: FONT.mono,
              fontSize: 16,
              color: COLORS.textMuted,
              marginBottom: 12,
            }}
          >
            <span>CONFIDENCE</span>
            <span style={{ color: COLORS.text }}>{Math.round(barFill * 100)}%</span>
          </div>
          <div
            style={{
              height: 8,
              background: COLORS.bgRaised,
              borderRadius: 4,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${barFill * 100}%`,
                background: `linear-gradient(90deg, ${COLORS.purple}, ${COLORS.mint})`,
              }}
            />
          </div>
        </div>

        {/* Stats row */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr 1fr",
            gap: 16,
            marginBottom: 36,
            opacity: rowOpacity(rowFrames[2]),
          }}
        >
          <Stat label="YIELD APR" value="+12.4%" tone={COLORS.mint} />
          <Stat label="SHARPE 30D" value="1.80" tone={COLORS.text} />
          <Stat label="MAX DRAWDOWN" value="-0.6%" tone={COLORS.magenta} />
        </div>

        {/* Dissent */}
        <div style={{ opacity: rowOpacity(rowFrames[3]), marginBottom: 24 }}>
          <div
            style={{
              fontFamily: FONT.mono,
              fontSize: 14,
              letterSpacing: 2,
              color: COLORS.magenta,
              marginBottom: 14,
              opacity: dissentPulse,
            }}
          >
            DISSENT · 2 BLOCKERS
          </div>
          <ul style={{ margin: 0, padding: 0, listStyle: "none", color: COLORS.text, fontSize: 22, lineHeight: 1.5 }}>
            <li style={{ opacity: rowOpacity(rowFrames[4]), display: "flex", gap: 12, marginBottom: 10 }}>
              <span style={{ color: COLORS.magenta }}>→</span>
              Reserve utilization at 92% triggers liquidation cascade — re-check before scaling
            </li>
            <li style={{ opacity: rowOpacity(rowFrames[5]), display: "flex", gap: 12 }}>
              <span style={{ color: COLORS.magenta }}>→</span>
              Pyth oracle staleness on USDC ≥ 30s — exit immediately
            </li>
          </ul>
        </div>

        {/* Citations */}
        <div style={{ opacity: rowOpacity(rowFrames[6]), display: "flex", flexWrap: "wrap", gap: 8 }}>
          {[
            "kamino.docs",
            "reserve_params",
            "agentic.market",
            "jaitan",
            "USDC_depth_30d",
            "bazaar.ai",
            "drift incident report",
          ].map((c) => (
            <span
              key={c}
              style={{
                fontFamily: FONT.mono,
                fontSize: 14,
                color: COLORS.cyan,
                background: "rgba(103, 232, 249, 0.08)",
                border: `1px solid ${COLORS.cyan}33`,
                borderRadius: 6,
                padding: "6px 10px",
              }}
            >
              {c}
            </span>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
};

const ActPill: React.FC = () => (
  <div
    style={{
      fontFamily: FONT.mono,
      color: COLORS.mint,
      border: `1.5px solid ${COLORS.mint}`,
      borderRadius: 999,
      padding: "10px 22px",
      fontSize: 18,
      letterSpacing: 3,
      fontWeight: 600,
      background: "rgba(34, 227, 166, 0.08)",
    }}
  >
    ACT
  </div>
);

const Stat: React.FC<{ label: string; value: string; tone: string }> = ({ label, value, tone }) => (
  <div
    style={{
      background: COLORS.bgRaised,
      border: `1px solid ${COLORS.border}`,
      borderRadius: 12,
      padding: "18px 20px",
    }}
  >
    <div style={{ fontFamily: FONT.mono, fontSize: 12, letterSpacing: 2, color: COLORS.textDim }}>
      {label}
    </div>
    <div
      style={{
        marginTop: 8,
        fontFamily: FONT.display,
        fontSize: 32,
        fontWeight: 600,
        color: tone,
      }}
    >
      {value}
    </div>
  </div>
);
