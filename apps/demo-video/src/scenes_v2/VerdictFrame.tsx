import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { COLORS, FONT } from "../theme";
import { TerminalFrame } from "./TerminalFrame";

// Citations modeled on landing's verdict-envelope but extended to 15 for the demo.
type Citation = { n: number; source: string; pk: string; rel: number };

const CITATIONS: Citation[] = [
  { n: 1, source: "Kamino vault docs · JLP-USDC", pk: "protocol_native", rel: 0.72 },
  { n: 2, source: "Howard Marks — On Risk", pk: "canon_marks", rel: 0.41 },
  { n: 3, source: "Kamino governance forum", pk: "protocol_native", rel: 0.39 },
  { n: 4, source: "Berkshire 2008 letter", pk: "canon_berkshire", rel: 0.34 },
  { n: 5, source: "Damodaran — Implied ERP", pk: "canon_damodaran", rel: 0.31 },
  { n: 6, source: "Pyth · SOL/USD oracle", pk: "market_data", rel: 0.29 },
  { n: 7, source: "DefiLlama · Kamino TVL 30d", pk: "market_data", rel: 0.28 },
  { n: 8, source: "Jupiter LP composition snapshot", pk: "protocol_native", rel: 0.27 },
  { n: 9, source: "Marks — Risk Revisited", pk: "canon_marks", rel: 0.25 },
  { n: 10, source: "Damodaran — Country Risk", pk: "canon_damodaran", rel: 0.24 },
  { n: 11, source: "Kamino audit registry", pk: "protocol_native", rel: 0.22 },
  { n: 12, source: "Berkshire 2017 letter", pk: "canon_berkshire", rel: 0.21 },
  { n: 13, source: "paysh · realtime fee feed", pk: "paysh_live", rel: 0.18 },
  { n: 14, source: "bazaar · vault param history", pk: "bazaar_live", rel: 0.17 },
  { n: 15, source: "Marks — Sea Change memo", pk: "canon_marks", rel: 0.16 },
];

const PK_COLOR: Record<string, string> = {
  protocol_native: COLORS.cyan,
  canon_marks: COLORS.purple,
  canon_damodaran: COLORS.purple,
  canon_berkshire: COLORS.purple,
  market_data: COLORS.mint,
  paysh_live: COLORS.mint,
  bazaar_live: COLORS.mint,
};

export const VerdictFrame: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const headerOp = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 16 });
  const dotsOp = spring({ frame: frame - 18, fps, config: { damping: 200 }, durationInFrames: 16 });
  const confOp = spring({ frame: frame - 30, fps, config: { damping: 200 }, durationInFrames: 16 });
  const citesHeaderOp = spring({ frame: frame - 60, fps, config: { damping: 200 }, durationInFrames: 14 });
  const dissentOp = spring({ frame: frame - 540, fps, config: { damping: 200 }, durationInFrames: 18 });
  const blockerOp = spring({ frame: frame - 600, fps, config: { damping: 200 }, durationInFrames: 18 });

  // citations stagger from frame 78, ~22 frames per citation (15 × 22 = 330 frames)
  const CITE_START = 78;
  const CITE_STAGGER = 22;

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TerminalFrame minHeight={920}>
        {/* Envelope header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: COLORS.textMuted,
            fontSize: 13,
            letterSpacing: 2,
            textTransform: "uppercase",
            opacity: headerOp,
          }}
        >
          <span>verdict envelope</span>
          <span style={{ fontFamily: FONT.mono, textTransform: "none", letterSpacing: 0 }}>
            kamino · dex · as_of 2024-08-12
          </span>
        </div>

        <div style={{ opacity: headerOp, marginTop: 14, color: COLORS.textMuted }}>
          <span style={{ color: COLORS.textDim }}>q:</span>{" "}
          <span style={{ color: COLORS.text }}>Is the JLP-USDC vault on Kamino worth depositing right now?</span>
        </div>

        {/* Verdict row + 7 dots */}
        <div
          style={{
            borderTop: `1px solid ${COLORS.border}`,
            marginTop: 22,
            paddingTop: 18,
            display: "flex",
            alignItems: "baseline",
            gap: 22,
            opacity: dotsOp,
          }}
        >
          <span style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            verdict
          </span>
          <span
            style={{
              color: COLORS.amber,
              fontSize: 38,
              fontWeight: 700,
              letterSpacing: 4,
              fontFamily: FONT.display,
              textTransform: "uppercase",
            }}
          >
            DEFER
          </span>
          {/* 7 persona dots, 2 dissent grayed */}
          <div style={{ display: "flex", gap: 8, marginLeft: 14 }}>
            {[0, 1, 2, 3, 4, 5, 6].map((i) => {
              const dissent = i >= 5; // last 2 are dissent
              return (
                <div
                  key={i}
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 6,
                    background: dissent ? COLORS.textDim : COLORS.amber,
                    opacity: dissent ? 0.5 : 0.9,
                  }}
                />
              );
            })}
          </div>
          <span style={{ color: COLORS.textMuted, marginLeft: "auto", fontFamily: FONT.mono, fontSize: 18 }}>
            conf <span style={{ color: COLORS.text }}>0.65</span>
          </span>
        </div>

        {/* Confidence band */}
        <div style={{ marginTop: 10, opacity: confOp }}>
          <div
            style={{
              height: 5,
              width: "100%",
              background: COLORS.bgRaised,
              borderRadius: 2,
              overflow: "hidden",
              border: `1px solid ${COLORS.border}`,
            }}
          >
            <div style={{ height: "100%", width: "65%", background: COLORS.amber, opacity: 0.6 }} />
          </div>
          <div style={{ color: COLORS.textDim, fontSize: 13, marginTop: 6, fontFamily: FONT.mono }}>
            0.65 — protocol-native solid; canon thin but converging
          </div>
        </div>

        {/* Citations */}
        <div style={{ marginTop: 22, opacity: citesHeaderOp }}>
          <div style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            citations · 15
          </div>
        </div>
        <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", columnGap: 36, rowGap: 6 }}>
          {CITATIONS.map((c, i) => {
            const revealAt = CITE_START + i * CITE_STAGGER;
            const op = spring({ frame: frame - revealAt, fps, config: { damping: 200 }, durationInFrames: 12 });
            const ty = interpolate(op, [0, 1], [4, 0]);
            return (
              <div
                key={c.n}
                style={{
                  opacity: op,
                  transform: `translateY(${ty}px)`,
                  display: "grid",
                  gridTemplateColumns: "26px 1fr auto",
                  alignItems: "baseline",
                  gap: 10,
                  fontSize: 14,
                  fontFamily: FONT.mono,
                }}
              >
                <span style={{ color: COLORS.textDim }}>[{c.n}]</span>
                <span style={{ color: COLORS.text }}>{c.source}</span>
                <span style={{ color: PK_COLOR[c.pk] ?? COLORS.textMuted, fontSize: 12 }}>
                  {c.pk} · {c.rel.toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>

        {/* Dissent */}
        <div
          style={{
            opacity: dissentOp,
            borderTop: `1px solid ${COLORS.border}`,
            marginTop: 24,
            paddingTop: 14,
          }}
        >
          <div style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            surviving dissent · 2 voices
          </div>
          <div style={{ color: COLORS.text, fontStyle: "italic", marginTop: 6, fontSize: 16 }}>
            <span style={{ color: COLORS.magenta, marginRight: 8 }}>›</span>
            Incident-free track record offsets the audit gap; panel could not resolve against corpus.
          </div>
        </div>

        {/* Blocker */}
        <div style={{ opacity: blockerOp, marginTop: 14 }}>
          <div style={{ color: COLORS.textMuted, fontSize: 13, letterSpacing: 2, textTransform: "uppercase" }}>
            blocker · what would change the answer
          </div>
          <div style={{ color: COLORS.text, marginTop: 6, fontSize: 16 }}>
            <span style={{ color: COLORS.textDim, marginRight: 8 }}>·</span>
            Will Kamino secure a credible third-party audit for the JLP-USDC strategy in the next 30 days?
          </div>
        </div>
      </TerminalFrame>
    </AbsoluteFill>
  );
};
