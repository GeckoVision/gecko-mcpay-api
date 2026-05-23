import { AbsoluteFill, useCurrentFrame } from "remotion";
import { COLORS } from "../theme";
import {
  useFade,
  useBeatTail,
  Eyebrow,
  Caption,
  StudioShot,
  TerminalFrame,
} from "./primitives";
import { BEATS } from "./timing";

// Beat 2 — Pre-contest [90–300 / 0:03–0:10]
// The earlier, simpler bot. Honest representation: the SAME real terminal,
// restricted to the contest-v1 feature set (breakout strategy + indexes only —
// no Oracle gate, no net-flow, fewer voices). Clearly labeled "contest v1".
// The still is composited from real captured panels (precontest-v1.png).

export const BeatPreContest: React.FC = () => {
  const frame = useCurrentFrame();
  const eyebrowOp = useFade(0, 16);
  const shotOp = useFade(10, 22);
  const capOp = useFade(110, 22);
  const tail = useBeatTail(BEATS.preContest.dur, 14);

  return (
    <AbsoluteFill style={{ backgroundColor: COLORS.bg, opacity: tail }}>
      <div style={{ position: "absolute", top: 64, left: 140, opacity: eyebrowOp }}>
        <Eyebrow color={COLORS.textMuted}>pre-contest · the earlier version</Eyebrow>
      </div>

      {/* Real terminal, contest-v1 subset, framed + labeled */}
      <div
        style={{
          position: "absolute",
          top: 130,
          left: 140,
          right: 140,
          bottom: 230,
          opacity: shotOp,
        }}
      >
        <TerminalFrame
          title="contest v1 · breakout + indexes"
          badge="v1"
          badgeColor={COLORS.textMuted}
        >
          <StudioShot
            asset="assets/studio/precontest-v1.png"
            localFrame={frame}
            durFrames={BEATS.preContest.dur}
            fit="cover"
            align="top center"
            zoomTo={1.04}
            radius={0}
          />
        </TerminalFrame>
      </div>

      <div style={{ position: "absolute", left: 140, bottom: 120, opacity: capOp }}>
        <Caption size={48} weight={700}>
          Pre-contest: a breakout bot.{" "}
          <span style={{ color: COLORS.textMuted, fontWeight: 400 }}>
            It chased signals.
          </span>
        </Caption>
      </div>
    </AbsoluteFill>
  );
};
