import { AbsoluteFill, Sequence } from "remotion";
import { COLORS } from "./theme";
import { V2_TIMING, V2_STARTS } from "./brand";
import { TitleCard } from "./scenes_v2/TitleCard";
import { QueryFrame } from "./scenes_v2/QueryFrame";
import { PanelFrame } from "./scenes_v2/PanelFrame";
import { VerdictFrame } from "./scenes_v2/VerdictFrame";
import { DeferFrame } from "./scenes_v2/DeferFrame";
import { EndCardV2 } from "./scenes_v2/EndCardV2";

export const DemoV2: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg }}>
      <Sequence from={V2_STARTS.title} durationInFrames={V2_TIMING.title}>
        <TitleCard />
      </Sequence>
      <Sequence from={V2_STARTS.query} durationInFrames={V2_TIMING.query}>
        <QueryFrame />
      </Sequence>
      <Sequence from={V2_STARTS.panel} durationInFrames={V2_TIMING.panel}>
        <PanelFrame />
      </Sequence>
      <Sequence from={V2_STARTS.verdict} durationInFrames={V2_TIMING.verdict}>
        <VerdictFrame />
      </Sequence>
      <Sequence from={V2_STARTS.defer} durationInFrames={V2_TIMING.defer}>
        <DeferFrame />
      </Sequence>
      <Sequence from={V2_STARTS.endCard} durationInFrames={V2_TIMING.endCard}>
        <EndCardV2 />
      </Sequence>
    </AbsoluteFill>
  );
};
