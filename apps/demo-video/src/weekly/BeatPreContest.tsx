import { AbsoluteFill, interpolate } from "remotion";
import { COLORS, FONT } from "../theme";
import { useFade, useBeatTail, Eyebrow, Caption } from "./primitives";
import { BEATS } from "./timing";

// Beat 2 — Pre-contest [120–390 / 0:04–0:13]
// Headline: "Last week: we shipped a trading bot into the OKX contest."
// Sub: "Like everyone else — it chased returns."
// Motif: a few mock ADX/RSI tiles, mint-on-dark — suggestive, not a full UI.

type Tile = { label: string; value: string; hint: string };
const TILES: Tile[] = [
  { label: "ADX", value: "31.4", hint: "trend strength" },
  { label: "RSI", value: "68", hint: "momentum" },
  { label: "ATR", value: "1.9%", hint: "volatility" },
];

export const BeatPreContest: React.FC = () => {
  const eyebrowOp = useFade(0, 16);
  const headOp = useFade(12, 22);
  const tilesOp = useFade(40, 20);
  const subOp = useFade(120, 22);
  const tail = useBeatTail(BEATS.preContest.dur, 14);
  const headY = interpolate(headOp, [0, 1], [12, 0]);

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
        <Eyebrow color={COLORS.textMuted}>last week</Eyebrow>
      </div>

      <div style={{ opacity: headOp, transform: `translateY(${headY}px)` }}>
        <Caption size={62} weight={700}>
          Last week: we shipped a trading bot
          <br />
          into the OKX contest.
        </Caption>
      </div>

      {/* Mock indicator tiles — mint-on-dark, terminal-native, suggestive only */}
      <div style={{ display: "flex", gap: 22, marginTop: 48, opacity: tilesOp }}>
        {TILES.map((t, i) => {
          const op = useFade(40 + i * 8, 16);
          return (
            <div
              key={t.label}
              style={{
                opacity: op,
                background: COLORS.bgPanel,
                border: `1px solid ${COLORS.border}`,
                borderRadius: 12,
                padding: "18px 26px",
                minWidth: 180,
              }}
            >
              <div
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 14,
                  letterSpacing: 3,
                  textTransform: "uppercase",
                  color: COLORS.textMuted,
                }}
              >
                {t.label}
              </div>
              <div
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 40,
                  fontWeight: 700,
                  color: COLORS.mint,
                  marginTop: 6,
                }}
              >
                {t.value}
              </div>
              <div
                style={{
                  fontFamily: FONT.mono,
                  fontSize: 13,
                  color: COLORS.textDim,
                  marginTop: 4,
                }}
              >
                {t.hint}
              </div>
            </div>
          );
        })}
        {/* Tiny suggestive price ticks */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 6,
            marginLeft: 8,
            opacity: tilesOp,
          }}
        >
          {[34, 52, 41, 63, 48, 70, 58, 78].map((h, i) => (
            <div
              key={i}
              style={{
                width: 10,
                height: h,
                background: COLORS.mintDim,
                borderTop: `2px solid ${COLORS.mint}`,
                borderRadius: 2,
              }}
            />
          ))}
        </div>
      </div>

      <div style={{ opacity: subOp, marginTop: 44 }}>
        <Caption size={34} color={COLORS.textMuted} weight={400} mono>
          Like everyone else — it chased returns.
        </Caption>
      </div>
    </AbsoluteFill>
  );
};
