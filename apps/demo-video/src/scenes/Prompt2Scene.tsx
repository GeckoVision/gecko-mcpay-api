import { COLORS } from "../theme";
import { TerminalScene, TerminalLine } from "../components/TerminalScene";

const PROMPT =
  "Use the gecko-trade-agent skill to deploy my strategy at /home/nan/.gecko/specs/example-kamino-dca.json in advisor mode.";

const LINES: TerminalLine[] = [
  { kind: "blank" },
  {
    kind: "action",
    spans: [{ text: "Skill(", color: COLORS.text }, { text: "gecko-trade-agent", color: COLORS.cyan }, { text: ")" }],
  },
  { kind: "subtle", text: "  ✓ Successfully loaded skill" },
  { kind: "blank" },
  {
    kind: "action",
    spans: [
      { text: "Bash(", color: COLORS.text },
      { text: "bb trade-agent --help", color: COLORS.cyan },
      { text: ")" },
    ],
  },
  { kind: "subtle", text: "  /bin/bash: line 1: bb: command not found" },
  { kind: "blank" },
  {
    kind: "action",
    spans: [
      { text: "Bash(", color: COLORS.text },
      { text: "uv run bb trade-agent --help", color: COLORS.cyan },
      { text: ")" },
    ],
  },
  { kind: "subtle", text: "  Usage: bb trade-agent [OPTIONS] COMMAND [ARGS]..." },
  { kind: "subtle", text: "  Long-running self-hosted trade-agent runtime." },
  { kind: "blank" },
  { kind: "result", text: "Preflight OK. Deploying in background.", indent: 0 },
  { kind: "blank" },
  {
    kind: "action",
    spans: [
      { text: "Bash(", color: COLORS.text },
      { text: "uv run bb trade-agent up --spec example-kamino-dca.json", color: COLORS.cyan },
      { text: ")" },
    ],
  },
  {
    kind: "subtle",
    spans: [
      { text: "  agent ", color: COLORS.textMuted },
      { text: "agent_1a50415b3f9f", color: COLORS.cyan, bold: true },
      { text: " up — mode=", color: COLORS.textMuted },
      { text: "advisor", color: COLORS.purple, bold: true },
      { text: "  spec=kamino-usdc-dca@0.1.0", color: COLORS.textMuted },
    ],
  },
  { kind: "blank" },
  { kind: "result", text: "Deployed. Foreground-tick-driven; journal confirms boot.", indent: 0 },
  { kind: "blank" },
  { kind: "heading", text: "State" },
  {
    kind: "body",
    spans: [
      { text: "  • " },
      { text: "agent_1a50415b3f9f", color: COLORS.cyan },
      { text: " — status=", color: COLORS.textMuted },
      { text: "running", color: COLORS.mint, bold: true },
      { text: ",  mode=", color: COLORS.textMuted },
      { text: "advisor", color: COLORS.purple, bold: true },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • Open positions: " },
      { text: "0", color: COLORS.cyan, bold: true },
      { text: "  (advisor mode never opens real positions)", color: COLORS.textMuted },
    ],
  },
  {
    kind: "body",
    spans: [
      { text: "  • Journal: ", color: COLORS.text },
      { text: "agent_started", color: COLORS.cyan },
      { text: " at 03:06:44 UTC", color: COLORS.textMuted },
    ],
  },
  { kind: "blank" },
  {
    kind: "subtle",
    text: "Steady-state cost ≈ $1.50/day per agent · cache-then-charge.",
  },
];

export const Prompt2Scene: React.FC = () => {
  return (
    <TerminalScene
      prompt={PROMPT}
      outputStartFrame={130}
      lines={LINES}
      lineStagger={9}
      fadeOut={[720, 750]}
    />
  );
};
