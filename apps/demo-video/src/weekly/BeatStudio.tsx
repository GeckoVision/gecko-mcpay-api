import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import {
  useBeatTail,
  Eyebrow,
  StudioShot,
  TerminalFrame,
  PointerCaption,
} from "./primitives";
import { BEATS } from "./timing";

// Beat 4 — The working bot [540–1080 / 0:18–0:36] — THE CENTERPIECE.
// Real screenshots of the live paper-mode studio at localhost:8265. We walk the
// screens with burn-in pointer captions: this is "how it works", not a pitch.
//
// 540 frames split into 5 shots:
//   0–90    full dashboard establish ("the live studio")
//   90–210  Agent Voices  (chart · regime · memory · risk)
//   210–330 Indexes       (live ADX / RSI / MFI / CHOP)
//   330–450 Gecko Oracle  (the gate)
//   450–540 Signal Feed   (live decision stream)

const SHOT = (from: number, dur: number) => ({ from, dur });
const SHOTS = {
  establish: SHOT(0, 90),
  voices: SHOT(90, 120),
  indexes: SHOT(210, 120),
  oracle: SHOT(330, 120),
  feed: SHOT(450, 90),
} as const;

// Available framing area (the stage the terminal window sits in).
const STAGE = { left: 140, right: 140, top: 120, bottom: 150 };
const STAGE_W = 1920 - STAGE.left - STAGE.right; // 1640
const STAGE_H = 1080 - STAGE.top - STAGE.bottom; // 810
const TITLEBAR = 50; // approx terminal title-bar height (chrome)

// One framed studio shot sized to the panel's natural aspect ratio so the real
// screenshot FILLS the window (no dead space) while staying crisp. The terminal
// window is centered on the stage; the pointer caption sits bottom-left.
const Shot: React.FC<{
  asset: string;
  imgW: number; // intrinsic px of the screenshot
  imgH: number;
  dur: number;
  title: string;
  badge?: string;
  label: string;
  sub?: string;
  accent?: string;
  panY?: number;
  zoomTo?: number;
}> = ({
  asset,
  imgW,
  imgH,
  dur,
  title,
  badge,
  label,
  sub,
  accent = COLORS.mint,
  panY = 0,
  zoomTo = 1.04,
}) => {
  const localFrame = useCurrentFrame();
  const aspect = imgW / imgH;
  // Fit the image area to the stage, preserving aspect. Reserve titlebar height.
  let imgAreaW = STAGE_W;
  let imgAreaH = imgAreaW / aspect;
  const maxImgH = STAGE_H - TITLEBAR;
  if (imgAreaH > maxImgH) {
    imgAreaH = maxImgH;
    imgAreaW = imgAreaH * aspect;
  }
  const winW = imgAreaW;
  const winH = imgAreaH + TITLEBAR;
  const left = STAGE.left + (STAGE_W - winW) / 2;
  const top = STAGE.top + (STAGE_H - winH) / 2;

  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left, top, width: winW, height: winH }}>
        <TerminalFrame title={title} badge={badge} badgeColor={accent}>
          <StudioShot
            asset={asset}
            localFrame={localFrame}
            durFrames={dur}
            fit="cover"
            align="top center"
            panY={panY}
            zoomTo={zoomTo}
            radius={0}
          />
        </TerminalFrame>
      </div>
      <div style={{ position: "absolute", left: left + 24, bottom: 70 }}>
        <PointerCaption
          localFrame={localFrame}
          delay={10}
          label={label}
          sub={sub}
          accent={accent}
        />
      </div>
    </AbsoluteFill>
  );
};

export const BeatStudio: React.FC = () => {
  const tail = useBeatTail(BEATS.studio.dur, 14);

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg, opacity: tail }}>
      {/* Persistent eyebrow so the viewer knows this is the real product */}
      <div style={{ position: "absolute", top: 56, left: 140 }}>
        <Eyebrow color={COLORS.mint}>the working bot · live paper studio</Eyebrow>
      </div>

      <Sequence from={SHOTS.establish.from} durationInFrames={SHOTS.establish.dur}>
        <Shot
          asset="assets/studio/full-dashboard.png"
          imgW={3840}
          imgH={2160}
          dur={SHOTS.establish.dur}
          title="localhost:8265 — My Strategy"
          badge="paper · live"
          label="This is the bot. Running now."
          sub="real paper data · PYTH · WIF · JUP · RAY · JTO"
          zoomTo={1.04}
        />
      </Sequence>

      <Sequence from={SHOTS.voices.from} durationInFrames={SHOTS.voices.dur}>
        <Shot
          asset="assets/studio/panel-agent-voices.png"
          imgW={3792}
          imgH={788}
          dur={SHOTS.voices.dur}
          title="Agent Voices — latest decisions"
          label="Agent Voices"
          sub="chart · regime · memory · risk — per symbol"
          panY={-4}
          zoomTo={1.05}
        />
      </Sequence>

      <Sequence from={SHOTS.indexes.from} durationInFrames={SHOTS.indexes.dur}>
        <Shot
          asset="assets/studio/panel-indexes.png"
          imgW={3792}
          imgH={970}
          dur={SHOTS.indexes.dur}
          title="Indexes — ADX / RSI / MFI / CHOP / bbw"
          label="Live indicators"
          sub="ADX · RSI · MFI · CHOP — with regime labels"
          panY={-4}
          zoomTo={1.05}
        />
      </Sequence>

      <Sequence from={SHOTS.oracle.from} durationInFrames={SHOTS.oracle.dur}>
        <Shot
          asset="assets/studio/panel-oracle.png"
          imgW={3792}
          imgH={328}
          dur={SHOTS.oracle.dur}
          title="Gecko Oracle — fundamentals verdict (live, grounded)"
          badge="the gate"
          label="Gecko Oracle gate"
          sub="grounded verdict · cites · pass / defer before any trade"
          accent={COLORS.cyan}
          zoomTo={1.03}
        />
      </Sequence>

      <Sequence from={SHOTS.feed.from} durationInFrames={SHOTS.feed.dur}>
        <Shot
          asset="assets/studio/panel-signal-feed.png"
          imgW={3792}
          imgH={928}
          dur={SHOTS.feed.dur}
          title="Signal Feed — live decision stream"
          label="Signal Feed"
          sub="every decision, logged · net-flow · 4-voice consensus"
          panY={-4}
          zoomTo={1.05}
        />
      </Sequence>
    </AbsoluteFill>
  );
};
