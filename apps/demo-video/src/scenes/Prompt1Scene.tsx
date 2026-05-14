import { COLORS } from "../theme";
import { TerminalScene, TerminalLine } from "../components/TerminalScene";

const PROMPT = "Should I deposit USDC into the Kamino USDC reserve right now?";

const LINES: TerminalLine[] = [
  { kind: "blank" },
  { kind: "action", text: "Running the trade research panel on this." },
  { kind: "subtle", text: "  Called gecko · 7-agent panel · investor canon", indent: 0 },
  { kind: "blank" },
  {
    kind: "result",
    spans: [
      { text: "Verdict: ", bold: true },
      { text: "defer", color: COLORS.amber, bold: true },
      { text: "   (confidence ", color: COLORS.textMuted },
      { text: "0.60", color: COLORS.cyan, bold: true },
      { text: ")", color: COLORS.textMuted },
    ],
  },
  { kind: "blank" },
  {
    kind: "body",
    text: "Don't deposit yet — not a no, but a not until one question is answered.",
    indent: 1,
  },
  { kind: "blank" },
  { kind: "heading", text: "Key drivers" },
  {
    kind: "body",
    spans: [
      { text: "  • " },
      { text: "Security: ", color: COLORS.cyan, bold: true },
      { text: "no recent audit confirmed in corpus — the blocker." },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • " },
      { text: "Risk band: ", color: COLORS.cyan, bold: true },
      { text: "elevated · smart-contract + concentration risk." },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • " },
      { text: "Fundamentals: ", color: COLORS.cyan, bold: true },
      { text: "TVL stable ≈ $3.16B · protocol healthy, under-disclosed." },
    ],
  },
  { kind: "blank" },
  {
    kind: "body",
    spans: [
      { text: "Surviving dissent (2): ", color: COLORS.magenta, bold: true },
      { text: "technical_analyst ", color: COLORS.text },
      { text: "(bearish), ", color: COLORS.textMuted },
      { text: "risk_manager ", color: COLORS.text },
      { text: "(elevated). Strategist: ", color: COLORS.textMuted },
      { text: '"observe."', color: COLORS.text },
    ],
  },
  { kind: "blank" },
  { kind: "heading", text: "The one question that flips the verdict" },
  {
    kind: "body",
    spans: [
      { text: "▎ ", color: COLORS.mint, bold: true },
      {
        text: "Has Kamino had a recent, comprehensive smart-contract audit?",
        color: COLORS.text,
        bold: true,
      },
    ],
  },
  { kind: "blank" },
  {
    kind: "subtle",
    spans: [
      { text: "Citations: ", color: COLORS.textMuted },
      { text: "15", color: COLORS.cyan, bold: true },
      { text: " — 2 live (Bazaar/Exa) · 13 canon (Marks, Damodaran)", color: COLORS.textMuted },
    ],
  },
  {
    kind: "subtle",
    text: "Not investment advice — oracle output. You make the call.",
  },
];

export const Prompt1Scene: React.FC = () => {
  return (
    <TerminalScene
      prompt={PROMPT}
      outputStartFrame={70}
      lines={LINES}
      lineStagger={11}
      fadeOut={[720, 750]}
    />
  );
};
