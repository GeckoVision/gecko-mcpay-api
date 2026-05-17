import { Composition } from "remotion";
import { FinalDemo } from "./FinalDemo";
import { DemoV2 } from "./DemoV2";
import { DURATION_FRAMES, FPS } from "./theme";
import { DEMO_V2_FRAMES } from "./brand";

export const Root: React.FC = () => {
  return (
    <>
      <Composition
        id="FinalDemo"
        component={FinalDemo}
        durationInFrames={DURATION_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="DemoV2"
        component={DemoV2}
        durationInFrames={DEMO_V2_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
