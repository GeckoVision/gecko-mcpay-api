import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";
import { TerminalFrame } from "./TerminalFrame";

type Persona = {
  name: string;
  role: string;
  stance: "act" | "defer" | "dissent";
  reasoning: string;
};

const PERSONAS: Persona[] = [
  { name: "value_investor", role: "Marks · drawdown lens", stance: "defer", reasoning: "audit gap pre-dates JLP-USDC strategy" },
  { name: "growth_analyst", role: "Damodaran · ERP lens", stance: "defer", reasoning: "reaching for yield in thin-evidence regime" },
  { name: "macro_strategist", role: "rate + flow lens", stance: "defer", reasoning: "SOL beta passes through JLP composition" },
  { name: "risk_officer", role: "Buffett · permanent capital", stance: "defer", reasoning: "liquidity assumption untested under stress" },
  { name: "fundamental_analyst", role: "protocol_native", stance: "act", reasoning: "rebalancer healthy · TVL stable 30d" },
  { name: "technical_analyst", role: "market_data", stance: "act", reasoning: "JLP basis within 2σ band, no dislocation" },
  { name: "contrarian", role: "dissent voice", stance: "dissent", reasoning: "incident-free track record offsets audit gap" },
];

const STAGGER = 18; // ~0.6s between persona reveals
const FIRST_REVEAL = 12;

const CONFIDENCE_TARGET = 0.65;
const CONF_RISE_START = FIRST_REVEAL + STAGGER * PERSONAS.length + 8;
const CONF_RISE_END = CONF_RISE_START + 90;

export const PanelFrame: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const conf = interpolate(frame, [CONF_RISE_START, CONF_RISE_END], [0, CONFIDENCE_TARGET], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TerminalFrame>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
          <span style={{ color: COLORS.textMuted, fontSize: 14, letterSpacing: 2, textTransform: "uppercase" }}>
            adversarial panel · 7 voices
          </span>
          <span style={{ color: COLORS.textDim, fontSize: 14, fontFamily: FONT.mono }}>
            kamino · dex · as_of 2024-08-12
          </span>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 36px" }}>
          {PERSONAS.map((p, i) => {
            const revealAt = FIRST_REVEAL + i * STAGGER;
            const op = spring({ frame: frame - revealAt, fps, config: { damping: 200 }, durationInFrames: 14 });
            const ty = interpolate(op, [0, 1], [6, 0]);
            return (
              <div
                key={p.name}
                style={{
                  opacity: op,
                  transform: `translateY(${ty}px)`,
                  borderLeft: `2px solid ${stanceColor(p.stance)}`,
                  paddingLeft: 14,
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ color: COLORS.text, fontWeight: 600 }}>{p.name}</span>
                  <span style={{ color: COLORS.textDim, fontSize: 13 }}>· {p.role}</span>
                  <span
                    style={{
                      marginLeft: "auto",
                      color: stanceColor(p.stance),
                      fontSize: 11,
                      letterSpacing: 2,
                      textTransform: "uppercase",
                      fontWeight: 700,
                    }}
                  >
                    {p.stance}
                  </span>
                </div>
                <div style={{ color: COLORS.textMuted, fontSize: 15, marginTop: 2 }}>
                  → {p.reasoning}
                </div>
              </div>
            );
          })}
        </div>

        {/* Confidence meter */}
        <div style={{ marginTop: 38 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ color: COLORS.textMuted, fontSize: 14, letterSpacing: 2, textTransform: "uppercase" }}>
              confidence
            </span>
            <span style={{ color: COLORS.text, fontFamily: FONT.mono, fontSize: 16 }}>{conf.toFixed(2)}</span>
          </div>
          <div
            style={{
              height: 6,
              width: "100%",
              background: COLORS.bgRaised,
              borderRadius: 3,
              overflow: "hidden",
              border: `1px solid ${COLORS.border}`,
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${conf * 100}%`,
                background: COLORS.verdictDefer,
                opacity: 0.85,
                boxShadow: `0 0 12px ${COLORS.verdictDefer}80`,
              }}
            />
          </div>
          <div style={{ color: COLORS.textDim, fontSize: 13, marginTop: 8 }}>
            {conf < 0.5 ? "panel forming…" : "5 of 7 voices align · 2 surviving dissent"}
          </div>
        </div>
      </TerminalFrame>
    </AbsoluteFill>
  );
};

const stanceColor = (s: Persona["stance"]) => {
  if (s === "act") return COLORS.mint;
  if (s === "defer") return COLORS.verdictDefer;
  return COLORS.magenta;
};
