// Gecko deck — shared tokens, components
// Design system inspired by Gecko v1 PPTX:
// - Light mode: near-white (#F1F3F7) + black text + blue accents
// - Dark mode: deep navy (#0E1420) + white text + blue accents
// - Headline: Archivo Black (condensed, heavy, all-caps)
// - Body: Inter
// - Tag/label: JetBrains Mono (monospace uppercase)
// - Motifs: header rail w/ section label + hairline, logo bottom-left,
//           "PITCHDECK — 2026" bottom-right, page number top-right,
//           black inverse tags, blue glitch squares, blue rect photo accents

const COLORS = {
  light: '#F1F3F7',
  lightAlt: '#E6EAF1',
  ink: '#0A0B10',
  muted: '#60636B',
  blue: '#1E56F5',
  blueDim: '#B8C7F9',
  dark: '#0E1420',
  darkAlt: '#161C2A',
  white: '#FFFFFF',
  green: '#14D98A',
  red: '#F45B5B',
};

const TYPE_SCALE = {
  hero: 140,
  title: 84,
  subtitle: 44,
  body: 32,
  bodyLg: 36,
  small: 26,
  mono: 22,
  tag: 20,
};

const SPACING = {
  paddingTop: 100,
  paddingBottom: 90,
  paddingX: 110,
  titleGap: 52,
  itemGap: 28,
};

const FONTS = {
  display: '"Archivo Black", "Archivo", Impact, sans-serif',
  body: '"Inter", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif',
  mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, monospace',
};

// Gecko logo mark — four connected dots around a center, from the v1 deck
function GeckoMark({ size = 28, color = COLORS.blue }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" style={{ flexShrink: 0 }}>
      {/* connecting lines */}
      <line x1="20" y1="20" x2="6" y2="12" stroke={color} strokeWidth="2.2" />
      <line x1="20" y1="20" x2="34" y2="12" stroke={color} strokeWidth="2.2" />
      <line x1="20" y1="20" x2="6" y2="28" stroke={color} strokeWidth="2.2" />
      <line x1="20" y1="20" x2="34" y2="28" stroke={color} strokeWidth="2.2" />
      {/* dots */}
      <circle cx="20" cy="20" r="5.5" fill={color} />
      <circle cx="6" cy="12" r="3.5" fill={color} />
      <circle cx="34" cy="12" r="3.5" fill={color} />
      <circle cx="6" cy="28" r="3.5" fill={color} />
      <circle cx="34" cy="28" r="3.5" fill={color} />
    </svg>
  );
}

function GeckoLogo({ light = false, size = 32 }) {
  const txtColor = light ? COLORS.white : COLORS.ink;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <GeckoMark size={size} color={COLORS.blue} />
      <span style={{
        fontFamily: FONTS.body,
        fontWeight: 700,
        fontSize: size * 0.9,
        color: txtColor,
        letterSpacing: '-0.02em',
      }}>
        gecko
      </span>
    </div>
  );
}

// The header rail at the top of every content slide:
// SECTION LABEL ────────────────── page #
function SlideHeader({ section, page, dark = false }) {
  const color = dark ? COLORS.blueDim : COLORS.blue;
  const line = dark ? 'rgba(184,199,249,0.35)' : 'rgba(30,86,245,0.35)';
  return (
    <div style={{
      position: 'absolute', top: 54, left: SPACING.paddingX, right: SPACING.paddingX,
      display: 'flex', alignItems: 'center', gap: 18, color,
      fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono, letterSpacing: '0.12em',
      textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      <span style={{ whiteSpace: 'nowrap' }}>{section}</span>
      <span style={{ flex: 1, height: 1, background: line }} />
      <span>{String(page).padStart(2, '0')}</span>
    </div>
  );
}

function SlideFooter({ dark = false }) {
  const color = dark ? COLORS.blueDim : COLORS.blue;
  return (
    <>
      <div style={{ position: 'absolute', bottom: 50, left: SPACING.paddingX }}>
        <GeckoLogo light={dark} size={28} />
      </div>
      <div style={{
        position: 'absolute', bottom: 58, right: SPACING.paddingX,
        fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono, letterSpacing: '0.12em',
        color, textTransform: 'uppercase', whiteSpace: 'nowrap',
      }}>
        PITCHDECK — 2026
      </div>
    </>
  );
}

// Monospace black tag (inverse label) — core Gecko motif
function Tag({ children, color = 'black', size = TYPE_SCALE.tag, style = {} }) {
  const bg = color === 'black' ? COLORS.ink
    : color === 'blue' ? COLORS.blue
    : color === 'white' ? COLORS.white
    : color;
  const fg = color === 'white' ? COLORS.ink : COLORS.white;
  return (
    <span style={{
      display: 'inline-block',
      padding: '8px 14px',
      background: bg,
      color: fg,
      fontFamily: FONTS.mono,
      fontSize: size,
      fontWeight: 500,
      letterSpacing: '0.08em',
      textTransform: 'uppercase',
      lineHeight: 1.1,
      whiteSpace: 'nowrap',
      ...style,
    }}>
      {children}
    </span>
  );
}

// Big slab title (Archivo Black uppercase)
function SlabTitle({ children, size = TYPE_SCALE.title, light = false, style = {} }) {
  return (
    <h1 style={{
      margin: 0,
      fontFamily: FONTS.display,
      fontSize: size,
      fontWeight: 900,
      lineHeight: 0.98,
      letterSpacing: '-0.015em',
      textTransform: 'uppercase',
      color: light ? COLORS.white : COLORS.ink,
      textWrap: 'balance',
      ...style,
    }}>
      {children}
    </h1>
  );
}

// Decorative blue glitch squares — v1 motif
function GlitchSquares({ cluster = 'tr', dark = false }) {
  const color = dark ? 'rgba(30,86,245,0.55)' : 'rgba(30,86,245,0.22)';
  const positions = {
    tr: [[0,0],[30,20],[60,8],[90,40],[18,60]],
    br: [[0,0],[-40,20],[-12,50],[30,35],[-60,70]],
    bl: [[0,0],[40,30],[12,60],[-20,20],[60,0]],
  }[cluster] || [];
  const base = {
    tr: { top: 140, right: 70 },
    br: { bottom: 160, right: 90 },
    bl: { bottom: 180, left: 70 },
  }[cluster];
  return (
    <div style={{ position: 'absolute', ...base, pointerEvents: 'none' }}>
      {positions.map(([x, y], i) => (
        <div key={i} style={{
          position: 'absolute', left: x, top: y,
          width: 10 + (i % 2) * 6, height: 10 + (i % 2) * 6,
          background: color,
        }} />
      ))}
    </div>
  );
}

// Striped placeholder with monospace caption
function ImagePlaceholder({ label, width = '100%', height = 300, dark = false, style = {} }) {
  const bg = dark ? COLORS.darkAlt : COLORS.lightAlt;
  const stripe = dark ? 'rgba(255,255,255,0.04)' : 'rgba(10,11,16,0.04)';
  const txt = dark ? 'rgba(255,255,255,0.55)' : 'rgba(10,11,16,0.55)';
  return (
    <div style={{
      width, height,
      background: `repeating-linear-gradient(135deg, ${bg} 0 18px, ${stripe} 18px 19px)`,
      border: `1px solid ${dark ? 'rgba(255,255,255,0.1)' : 'rgba(10,11,16,0.1)'}`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
      color: txt, textTransform: 'uppercase', letterSpacing: '0.12em',
      ...style,
    }}>
      {label}
    </div>
  );
}

// The "desaturated photo on blue rectangle" motif
function PhotoCard({ label, width = 420, height = 520 }) {
  return (
    <div style={{ position: 'relative', width, height }}>
      {/* blue accent rectangle offset behind */}
      <div style={{
        position: 'absolute', inset: '30px -30px -30px 30px',
        background: COLORS.blue, opacity: 0.9,
      }} />
      <ImagePlaceholder label={label} width="100%" height="100%"
        style={{ position: 'absolute', inset: 0, filter: 'grayscale(1)' }} />
    </div>
  );
}

Object.assign(window, {
  COLORS, TYPE_SCALE, SPACING, FONTS,
  GeckoMark, GeckoLogo, SlideHeader, SlideFooter,
  Tag, SlabTitle, GlitchSquares, ImagePlaceholder, PhotoCard,
});
