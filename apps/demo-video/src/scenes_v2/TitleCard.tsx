import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

// Title card is now a still render of the brand cover image (1920x1080).
// Cover image carries its own baked-in typography — no overlay text.
export const TitleCard: React.FC = () => {
  const frame = useCurrentFrame();
  // Subtle fade-in on the front, hold, soft pre-cut fade at the tail.
  const opacity = interpolate(frame, [0, 15, 135, 150], [0, 1, 1, 0.95], {
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ opacity, backgroundColor: "#000" }}>
      <Img
        src={staticFile("assets/cover.jpg")}
        style={{ width: "100%", height: "100%", objectFit: "cover" }}
      />
    </AbsoluteFill>
  );
};
