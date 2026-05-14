import { AbsoluteFill } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { slide } from "@remotion/transitions/slide";

import { COLORS, SCENES, TRANSITION } from "./theme";
import { TitleScene } from "./scenes/TitleScene";
import { Prompt1Scene } from "./scenes/Prompt1Scene";
import { ChainProofScene } from "./scenes/ChainProofScene";
import { Prompt2Scene } from "./scenes/Prompt2Scene";
import { Prompt3Scene } from "./scenes/Prompt3Scene";
import { MoatStripScene } from "./scenes/MoatStripScene";
import { EndCardScene } from "./scenes/EndCardScene";

export const FinalDemo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={SCENES.title}>
          <TitleScene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.prompt1}>
          <Prompt1Scene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.chainProof}>
          <ChainProofScene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={slide({ direction: "from-right" })}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.prompt2}>
          <Prompt2Scene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.prompt3}>
          <Prompt3Scene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.moatStrip}>
          <MoatStripScene />
        </TransitionSeries.Sequence>

        <TransitionSeries.Transition
          presentation={fade()}
          timing={linearTiming({ durationInFrames: TRANSITION })}
        />

        <TransitionSeries.Sequence durationInFrames={SCENES.endCard}>
          <EndCardScene />
        </TransitionSeries.Sequence>
      </TransitionSeries>
    </AbsoluteFill>
  );
};
