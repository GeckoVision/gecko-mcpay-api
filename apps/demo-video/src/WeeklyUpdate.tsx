import { AbsoluteFill, Sequence, useCurrentFrame } from "remotion";
import { COLORS, FONT } from "./theme";
import { BEATS, WEEKLY_FRAMES } from "./weekly/timing";
import { BeatTitle } from "./weekly/BeatTitle";
import { BeatPreContest } from "./weekly/BeatPreContest";
import { BeatReckoning } from "./weekly/BeatReckoning";
import { BeatReframe } from "./weekly/BeatReframe";
import { BeatValidation } from "./weekly/BeatValidation";
import { BeatRoadmap } from "./weekly/BeatRoadmap";
import { BeatEndCard } from "./weekly/BeatEndCard";

// WeeklyUpdate — 60s weekly build update. 1920×1080, 30fps, 1800 frames.
// 7 locked beats. Stark dark editorial, mint accent, burn-in captions.
// Reads fully muted; minimal motion; no gradients/animated web3 backdrops.

// Thin persistent progress strip + brand mark — documentary, calm, always-on.
const ProgressFooter: React.FC = () => {
  const frame = useCurrentFrame();
  const pct = Math.min(1, frame / WEEKLY_FRAMES);
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: 0,
          bottom: 0,
          height: 4,
          width: `${pct * 100}%`,
          background: COLORS.mint,
          opacity: 0.7,
        }}
      />
      <div
        style={{
          position: "absolute",
          right: 56,
          bottom: 36,
          fontFamily: FONT.mono,
          fontSize: 16,
          letterSpacing: 4,
          textTransform: "uppercase",
          color: COLORS.textDim,
        }}
      >
        gecko · weekly
      </div>
    </>
  );
};

export const WeeklyUpdate: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <Sequence from={BEATS.title.from} durationInFrames={BEATS.title.dur}>
        <BeatTitle />
      </Sequence>
      <Sequence from={BEATS.preContest.from} durationInFrames={BEATS.preContest.dur}>
        <BeatPreContest />
      </Sequence>
      <Sequence from={BEATS.reckoning.from} durationInFrames={BEATS.reckoning.dur}>
        <BeatReckoning />
      </Sequence>
      <Sequence from={BEATS.reframe.from} durationInFrames={BEATS.reframe.dur}>
        <BeatReframe />
      </Sequence>
      <Sequence from={BEATS.validation.from} durationInFrames={BEATS.validation.dur}>
        <BeatValidation />
      </Sequence>
      <Sequence from={BEATS.roadmap.from} durationInFrames={BEATS.roadmap.dur}>
        <BeatRoadmap />
      </Sequence>
      <Sequence from={BEATS.endCard.from} durationInFrames={BEATS.endCard.dur}>
        <BeatEndCard />
      </Sequence>
      <ProgressFooter />
    </AbsoluteFill>
  );
};
