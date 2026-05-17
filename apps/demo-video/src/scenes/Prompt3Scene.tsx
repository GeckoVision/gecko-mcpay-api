import { COLORS } from "../theme";
import { TerminalScene, TerminalLine } from "../components/TerminalScene";

const PROMPT = "What is my agent doing right now? Then fire a fresh verdict from the panel.";

const LINES: TerminalLine[] = [
  { kind: "blank" },
  {
    kind: "action",
    spans: [
      { text: "Bash(", color: COLORS.text },
      { text: "uv run bb trade-agent inspect agent_1a50415b3f9f", color: COLORS.cyan },
      { text: ")" },
    ],
  },
  {
    kind: "subtle",
    spans: [
      { text: "  agent ", color: COLORS.textMuted },
      { text: "agent_1a50415b3f9f", color: COLORS.cyan, bold: true },
      { text: "  status=", color: COLORS.textMuted },
      { text: "running", color: COLORS.mint, bold: true },
      { text: "  mode=advisor", color: COLORS.textMuted },
    ],
  },
  { kind: "subtle", text: "  open positions: 0" },
  { kind: "subtle", text: "  recent journal (1): agent_started at 03:06:44 UTC" },
  { kind: "blank" },
  {
    kind: "action",
    spans: [
      { text: "Bash(", color: COLORS.text },
      { text: "uv run bb trade-agent reverdict --tier basic", color: COLORS.cyan },
      { text: ")" },
    ],
  },
  {
    kind: "subtle",
    text: "  firing manual basic verdict (protocol=kamino, idea=session:kamino-usdc-dca)...",
  },
  {
    kind: "subtle",
    spans: [
      { text: "  verdict=", color: COLORS.textMuted },
      { text: "defer", color: COLORS.amber, bold: true },
      { text: "  confidence=", color: COLORS.textMuted },
      { text: "0.70", color: COLORS.cyan, bold: true },
      { text: "  citations=15  dissent=2", color: COLORS.textMuted },
    ],
  },
  { kind: "blank" },
  { kind: "result", text: "Fresh panel verdict landed in the journal.", indent: 0 },
  { kind: "blank" },
  { kind: "heading", text: "Status" },
  {
    kind: "body",
    spans: [
      { text: "  • " },
      { text: "agent_1a50415b3f9f", color: COLORS.cyan },
      { text: " — ", color: COLORS.textMuted },
      { text: "running", color: COLORS.mint, bold: true },
      { text: ", advisor mode", color: COLORS.textMuted },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • Open positions: 0  ", color: COLORS.text },
      { text: "(advisor never opens real ones)", color: COLORS.textMuted },
    ],
  },
  { kind: "blank" },
  { kind: "heading", text: "Fresh panel verdict (manual, basic tier)" },
  {
    kind: "body",
    spans: [
      { text: "  • verdict = " },
      { text: "defer", color: COLORS.amber, bold: true },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • confidence = " },
      { text: "0.70", color: COLORS.cyan, bold: true },
      { text: "   ", color: COLORS.textMuted },
      { text: "(0.60 → 0.70 on the second pass)", color: COLORS.textMuted },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • citations = " },
      { text: "15", color: COLORS.cyan, bold: true },
      { text: "   • dissent = " },
      { text: "2 (surviving)", color: COLORS.magenta, bold: true },
    ],
  },
  { kind: "blank" },
  {
    kind: "subtle",
    text: "Reverdict landed as verdict_called at 03:08:43 UTC — defer pending audit.",
  },
];

export const Prompt3Scene: React.FC = () => {
  return (
    <TerminalScene
      prompt={PROMPT}
      outputStartFrame={110}
      lines={LINES}
      lineStagger={9}
      fadeOut={[720, 750]}
    />
  );
};
