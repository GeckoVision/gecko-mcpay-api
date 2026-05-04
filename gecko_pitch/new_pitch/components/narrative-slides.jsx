// Gecko — Narrative Pitch deck slides
// N01Thesis … N10Ask  (10 slides, 1920×1080)
// Design tokens live in common.jsx (loaded first)

const slideShell = (dark) => ({
  background: dark ? COLORS.dark : COLORS.light,
  width: '100%', height: '100%',
  position: 'relative', overflow: 'hidden',
  fontFamily: FONTS.body,
  color: dark ? COLORS.white : COLORS.ink,
});

// ─────────────────────────────────────────────────────────────
// 01 · THESIS  (dark)
// "Capability is commoditized. Judgment is scarce."
// ─────────────────────────────────────────────────────────────
function N01Thesis() {
  return (
    <section data-label="Thesis" style={slideShell(true)}>
      {/* subtle radial tints */}
      <div style={{
        position: 'absolute', inset: 0,
        background: `radial-gradient(ellipse at 75% 25%, rgba(30,86,245,0.16), transparent 55%),
                     radial-gradient(ellipse at 15% 80%, rgba(30,86,245,0.09), transparent 45%)`,
        pointerEvents: 'none',
      }} />
      {/* glitch squares */}
      {[[120,180,14],[240,120,8],[1680,240,12],[1760,360,8],[180,820,16],[320,920,8],
        [1540,820,10],[1720,880,14],[1820,640,8]].map(([x,y,s],i)=>(
        <div key={i} style={{
          position: 'absolute', left: x, top: y, width: s, height: s,
          background: `rgba(30,86,245,${0.22 + (i%3)*0.14})`,
        }} />
      ))}

      {/* top — gecko logo centered */}
      <div style={{
        position: 'absolute', top: 72, left: 0, right: 0,
        display: 'flex', justifyContent: 'center',
      }}>
        <GeckoLogo light size={48} />
      </div>

      {/* hero title block */}
      <div style={{
        position: 'absolute',
        top: '50%', left: 0, right: 0,
        transform: 'translateY(-56%)',
        textAlign: 'center',
        padding: `0 ${SPACING.paddingX}px`,
      }}>
        <h1 style={{
          margin: 0,
          fontFamily: FONTS.display,
          fontSize: TYPE_SCALE.hero,
          fontWeight: 900,
          lineHeight: 0.96,
          letterSpacing: '-0.015em',
          textTransform: 'uppercase',
          textWrap: 'balance',
        }}>
          <span style={{ color: 'rgba(255,255,255,0.35)' }}>CAPABILITY IS</span>{' '}
          <span style={{ color: COLORS.white }}>COMMODITIZED.</span>
          <br />
          <span style={{ color: COLORS.blue }}>JUDGMENT</span>{' '}
          <span style={{ color: COLORS.white }}>IS SCARCE.</span>
        </h1>

        <div style={{
          marginTop: 44,
          fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono,
          letterSpacing: '0.1em', textTransform: 'uppercase',
          color: COLORS.blueDim,
          lineHeight: 1.5,
        }}>
          Bazaar makes capability tradeable.&nbsp;&nbsp;·&nbsp;&nbsp;Gecko makes judgment tradeable.
        </div>
      </div>

      {/* bottom founders line */}
      <div style={{
        position: 'absolute', bottom: 72, left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
        color: 'rgba(255,255,255,0.5)', letterSpacing: '0.1em', textTransform: 'uppercase',
      }}>
        <span>ERNANI BRITTO · LETICIA ALMEIDA</span>
        <span style={{ color: COLORS.blueDim }}>SEED · $250K</span>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 02 · CAIO — the persona  (light)
// ─────────────────────────────────────────────────────────────
function N02Caio() {
  const rows = [
    ['ROLE', 'Solo founder, pre-revenue SaaS.'],
    ['SITUATION', '3 projects deep. No senior to ping. 20h/week in ChatGPT.'],
    ['COST', '6 months shipped. Zero users. $0 earned.'],
  ];
  return (
    <section data-label="Caio" style={slideShell(false)}>
      <SlideHeader section="THE FOUNDER" page={2} />

      {/* left — data table */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        width: 860,
      }}>
        <SlabTitle size={64}>
          MEET<br />
          <span style={{ color: COLORS.blue }}>CAIO.</span>
        </SlabTitle>

        {/* data rows */}
        <div style={{
          marginTop: 48,
          borderTop: `1px solid rgba(10,11,16,0.12)`,
        }}>
          {rows.map(([label, body]) => (
            <div key={label} style={{
              display: 'grid',
              gridTemplateColumns: '200px 1fr',
              gap: 24,
              padding: '28px 0',
              borderBottom: `1px solid rgba(10,11,16,0.12)`,
            }}>
              <div style={{
                fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
                letterSpacing: '0.12em', textTransform: 'uppercase',
                color: COLORS.muted,
                paddingTop: 3,
              }}>{label}</div>
              <div style={{
                fontSize: 26, lineHeight: 1.3, color: COLORS.ink,
              }}>{body}</div>
            </div>
          ))}
        </div>

        {/* quote */}
        <div style={{ marginTop: 48 }}>
          <h2 style={{
            margin: 0,
            fontFamily: FONTS.display,
            fontSize: 48,
            fontWeight: 900,
            lineHeight: 1.05,
            letterSpacing: '-0.01em',
            textTransform: 'uppercase',
            color: COLORS.ink,
          }}>
            "AM I BUILDING{' '}
            <span style={{ color: COLORS.blue }}>THE WRONG THING</span>{' '}
            AGAIN?"
          </h2>
        </div>
      </div>

      {/* right — photo card */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        right: SPACING.paddingX,
        width: 420,
      }}>
        <PhotoCard label="CAIO · 3AM SESSION" width={420} height={560} />
        <div style={{
          marginTop: 20,
          fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
          letterSpacing: '0.12em', textTransform: 'uppercase',
          color: COLORS.muted,
        }}>
          SOLO FOUNDER · SAO PAULO
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 03 · DARK ROOM  (dark)
// Without senior judgment, cost of building wrong is invisible
// ─────────────────────────────────────────────────────────────
function N03DarkRoom() {
  const stats = [
    ['90%', 'OF SOLO FOUNDERS', 'build without structured peer review'],
    ['20H', 'PER WEEK', 'lost to tools that just agree with them'],
    ['$0', 'IN RETURN', 'for 6 months of building the wrong thing'],
  ];
  return (
    <section data-label="Dark Room" style={slideShell(true)}>
      <SlideHeader section="THE PROBLEM" page={3} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={80} light>
          HE IS BUILDING<br />IN THE{' '}
          <span style={{ color: COLORS.blue }}>DARK.</span>
        </SlabTitle>
        <p style={{
          marginTop: 32, fontSize: 28, lineHeight: 1.4,
          color: 'rgba(255,255,255,0.65)',
          maxWidth: 900,
        }}>
          ChatGPT agrees. Product Hunt votes are random.
          There is no senior PM to say "wrong direction."
          Insight without adversarial challenge is just expensive confirmation bias.
        </p>
      </div>

      {/* stat strip */}
      <div style={{
        position: 'absolute',
        bottom: 130,
        left: 0, right: 0,
        borderTop: `1px solid rgba(184,199,249,0.25)`,
        borderBottom: `1px solid rgba(184,199,249,0.25)`,
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
      }}>
        {stats.map(([num, label, desc]) => (
          <div key={num} style={{
            padding: '38px 60px',
            borderRight: `1px solid rgba(184,199,249,0.15)`,
          }}>
            <div style={{
              fontFamily: FONTS.display,
              fontSize: 80,
              fontWeight: 900,
              lineHeight: 1,
              color: COLORS.blue,
              letterSpacing: '-0.02em',
            }}>{num}</div>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 18,
              letterSpacing: '0.14em', textTransform: 'uppercase',
              color: COLORS.blueDim, marginTop: 10,
            }}>{label}</div>
            <div style={{
              fontSize: 22, color: 'rgba(255,255,255,0.55)',
              marginTop: 8, lineHeight: 1.3,
            }}>{desc}</div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 04 · THE SHIFT  (light)
// Panel-based verdict replaces solo guesswork
// ─────────────────────────────────────────────────────────────
function N04Shift() {
  const beforeRows = [
    'Ask one AI — it agrees with you',
    'No structured dissent recorded',
    'Guess which signal to trust',
    'Restart if idea was wrong',
  ];
  const afterRows = [
    'Five adversarial voices, one verdict',
    'Signed dissent, cited sources',
    'Reproducible hash per session',
    '90-day session — refine, don\'t restart',
  ];
  return (
    <section data-label="The Shift" style={slideShell(false)}>
      <SlideHeader section="THE SOLUTION" page={4} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={68}>
          INSTEAD OF ONE YES-MAN,<br />
          <span style={{ color: COLORS.blue }}>CONVENE A PANEL.</span>
        </SlabTitle>
      </div>

      {/* two-column compare */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 220,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
        display: 'flex',
        alignItems: 'stretch',
        gap: 0,
      }}>
        {/* BEFORE card */}
        <div style={{
          flex: 1,
          background: COLORS.white,
          border: `1px solid rgba(10,11,16,0.12)`,
          padding: '36px 40px',
        }}>
          <div style={{
            fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
            letterSpacing: '0.12em', textTransform: 'uppercase',
            color: COLORS.muted, marginBottom: 28,
          }}>BEFORE</div>
          {beforeRows.map((r) => (
            <div key={r} style={{
              display: 'flex', alignItems: 'flex-start', gap: 16,
              padding: '18px 0',
              borderBottom: `1px solid rgba(10,11,16,0.07)`,
              fontSize: 24, color: COLORS.muted, lineHeight: 1.3,
            }}>
              <span style={{ color: 'rgba(10,11,16,0.22)', marginTop: 3 }}>✕</span>
              {r}
            </div>
          ))}
        </div>

        {/* arrow */}
        <div style={{
          width: 100, display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: FONTS.display, fontSize: 64, color: COLORS.blue,
          flexShrink: 0,
        }}>→</div>

        {/* AFTER card */}
        <div style={{
          flex: 1,
          background: COLORS.dark,
          padding: '36px 40px',
        }}>
          <div style={{
            fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
            letterSpacing: '0.12em', textTransform: 'uppercase',
            color: COLORS.blueDim, marginBottom: 28,
          }}>AFTER</div>
          {afterRows.map((r) => (
            <div key={r} style={{
              display: 'flex', alignItems: 'flex-start', gap: 16,
              padding: '18px 0',
              borderBottom: `1px solid rgba(255,255,255,0.07)`,
              fontSize: 24, color: COLORS.white, lineHeight: 1.3,
            }}>
              <span style={{ color: COLORS.blue, marginTop: 3 }}>✓</span>
              {r}
            </div>
          ))}
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 05 · PRODUCT  (dark)
// Three tools — classify, research, ask
// ─────────────────────────────────────────────────────────────
function N05Product() {
  const tools = [
    {
      name: 'gecko_classify',
      tag: 'INSTANT',
      stat: '< 2s',
      desc: 'Pass an idea. Get GO / REFINE / KILL with a signed verdict hash. Five adversarial voices, one output.',
    },
    {
      name: 'gecko_research',
      tag: 'DEEP',
      stat: '< 90s',
      desc: 'Cite market data, competitor filings, founder precedents. Session persisted — resume any time in 90 days.',
    },
    {
      name: 'gecko_ask',
      tag: 'CONVERSATIONAL',
      stat: 'LIVE',
      desc: 'Drill into any dimension of the verdict. Context from the full session. Grounded, not sycophantic.',
    },
  ];
  return (
    <section data-label="Product" style={slideShell(true)}>
      <SlideHeader section="PRODUCT" page={5} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={72} light>
          THREE CALLS.<br />
          <span style={{ color: COLORS.blue }}>ONE VERDICT.</span>
        </SlabTitle>
      </div>

      {/* tool cards */}
      <div style={{
        position: 'absolute',
        bottom: 140,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 22,
      }}>
        {tools.map(({ name, tag, stat, desc }) => (
          <div key={name} style={{
            background: 'rgba(30,86,245,0.08)',
            border: `1px solid rgba(184,199,249,0.25)`,
            padding: '34px 36px 32px',
          }}>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 26,
              color: COLORS.white, letterSpacing: '-0.01em',
              marginBottom: 10,
            }}>{name}</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
              <Tag color="blue" size={16}>{tag}</Tag>
              <span style={{
                fontFamily: FONTS.mono, fontSize: 18,
                color: COLORS.blue, letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}>{stat}</span>
            </div>
            <div style={{
              fontSize: 22, color: 'rgba(255,255,255,0.7)', lineHeight: 1.4,
            }}>{desc}</div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 06 · EVIDENCE  (light)
// We ran Gecko on Gecko — it said REFINE
// ─────────────────────────────────────────────────────────────
function N06Evidence() {
  const dissent = [
    {
      role: 'CEO',
      verdict: 'GO',
      note: '"Market timing is right. Agent-native UX is a 6-month window."',
    },
    {
      role: 'CTO',
      verdict: 'REFINE',
      note: '"The settlement layer needs a trust-minimized audit trail before mainnet."',
    },
    {
      role: 'PM',
      verdict: 'REFINE',
      note: '"ICP is too broad. Narrow to pre-seed solo founders first."',
    },
  ];
  return (
    <section data-label="Evidence" style={slideShell(false)}>
      <SlideHeader section="EVIDENCE" page={6} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        width: 760,
      }}>
        <SlabTitle size={68}>
          WE RAN GECKO<br />ON{' '}
          <span style={{ color: COLORS.blue }}>GECKO.</span>
        </SlabTitle>
        <p style={{
          marginTop: 24, fontSize: 26, lineHeight: 1.4, color: COLORS.muted,
          maxWidth: 700,
        }}>
          Five voices. Public disagreement. Verdict: <strong style={{ color: COLORS.ink }}>REFINE</strong>.
          CEO and CTO disagreed on-record — that's the product working.
        </p>
      </div>

      {/* VerdictCard */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        right: SPACING.paddingX,
        width: 480,
        background: COLORS.white,
        border: `2px solid ${COLORS.blue}`,
        padding: '32px 36px',
      }}>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 16,
          letterSpacing: '0.12em', textTransform: 'uppercase',
          color: COLORS.blue, marginBottom: 14,
        }}>VERDICT · SIGNED</div>
        <div style={{
          fontFamily: FONTS.display, fontSize: 84,
          fontWeight: 900, lineHeight: 1,
          color: COLORS.blue, textTransform: 'uppercase',
          letterSpacing: '-0.02em',
        }}>REFINE</div>
        <div style={{
          marginTop: 16,
          fontFamily: FONTS.mono, fontSize: 14,
          color: COLORS.muted, letterSpacing: '0.08em',
        }}>sha256·a3f7c8d2e1…</div>
        <div style={{
          marginTop: 16,
          borderTop: `1px solid rgba(10,11,16,0.12)`,
          paddingTop: 16,
          display: 'flex', justifyContent: 'space-between',
          fontFamily: FONTS.mono, fontSize: 18,
          color: COLORS.ink, letterSpacing: '0.06em',
        }}>
          <span>5 / 5 VOICES</span>
          <span>$0.0107</span>
        </div>
      </div>

      {/* disagreement cards */}
      <div style={{
        position: 'absolute',
        bottom: 120,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 22,
      }}>
        {dissent.map(({ role, verdict, note }) => (
          <div key={role} style={{
            background: COLORS.white,
            borderLeft: `3px solid ${COLORS.blue}`,
            padding: '24px 28px',
            boxShadow: '0 1px 3px rgba(10,11,16,0.06)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 14 }}>
              <span style={{
                fontFamily: FONTS.mono, fontSize: 16,
                letterSpacing: '0.12em', textTransform: 'uppercase',
                color: COLORS.blue,
              }}>{role}</span>
              <Tag color={verdict === 'GO' ? 'blue' : 'black'} size={14}>{verdict}</Tag>
            </div>
            <div style={{ fontSize: 22, lineHeight: 1.35, color: COLORS.muted }}>
              {note}
            </div>
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 07 · WHY NOW  (dark)
// Three forces that make this the moment
// ─────────────────────────────────────────────────────────────
function N07WhyNow() {
  const reasons = [
    {
      tag: 'AGENT-MEDIATED',
      title: 'AGENTS BUY TOOLS',
      desc: 'Claude Code, GPT-4o, Gemini CLI — all have tool-use. MCP is the distribution layer. Gecko ships as a skill on day one.',
    },
    {
      tag: 'MICRO-COST',
      title: 'UNIT ECONOMICS WORK',
      desc: 'x402 on Solana makes $0.01 verdict payments viable. No subscription, no minimum. Pay per judgment, keep every insight.',
    },
    {
      tag: 'COMPOSABLE',
      title: 'SESSION AS ASSET',
      desc: 'A 90-day session is a knowledge object: cited, hashed, resumable. Not a chat log — a judgment record with provenance.',
    },
  ];
  return (
    <section data-label="Why Now" style={slideShell(true)}>
      <SlideHeader section="WHY NOW" page={7} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={72} light>
          THREE FORCES.<br />
          <span style={{ color: COLORS.blue }}>ONE WINDOW.</span>
        </SlabTitle>
      </div>

      {/* cards */}
      <div style={{
        position: 'absolute',
        bottom: 140,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 22,
      }}>
        {reasons.map(({ tag, title, desc }) => (
          <div key={tag} style={{
            background: 'rgba(30,86,245,0.08)',
            border: `1px solid rgba(184,199,249,0.25)`,
            padding: '34px 36px 32px',
          }}>
            <Tag color="blue" size={16}>{tag}</Tag>
            <div style={{
              fontFamily: FONTS.display, fontSize: 34,
              fontWeight: 900, textTransform: 'uppercase',
              color: COLORS.white, lineHeight: 1.1,
              marginTop: 20, marginBottom: 16,
            }}>{title}</div>
            <div style={{
              fontSize: 22, color: 'rgba(255,255,255,0.68)', lineHeight: 1.4,
            }}>{desc}</div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 08 · MOAT  (light)
// Three defensible advantages
// ─────────────────────────────────────────────────────────────
function N08Moat() {
  const moats = [
    {
      n: '01',
      title: 'ENCODED JUDGMENT',
      desc: 'The 5-voice panel is not a chat wrapper. It is a designed adversarial protocol — optimist, pessimist, market analyst, technical skeptic, devil\'s advocate. Hard to replicate without the prompt engineering layer.',
    },
    {
      n: '02',
      title: 'SESSIONS AS ASSETS',
      desc: 'Each session is a signed, hashable record: verdict, dissent, cited sources, timestamp. A founder can carry a Gecko session to investors, co-founders, or their future self. That\'s a knowledge primitive Perplexity doesn\'t produce.',
    },
    {
      n: '03',
      title: 'SETTLEMENT LAYER',
      desc: 'x402 micropayments mean verdict quality compounds into contributor reputation. Who gave the best market read? Which voice called the pivot 90 days early? That signal becomes the moat when we open the panel to external contributors.',
    },
  ];
  return (
    <section data-label="Moat" style={slideShell(false)}>
      <SlideHeader section="DEFENSIBILITY" page={8} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={68}>
          WHY THIS IS{' '}
          <span style={{ color: COLORS.blue }}>HARD TO COPY.</span>
        </SlabTitle>
      </div>

      {/* feature rows */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 220,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
        display: 'flex',
        flexDirection: 'column',
        gap: 0,
      }}>
        {moats.map(({ n, title, desc }, i) => (
          <div key={n} style={{
            display: 'grid',
            gridTemplateColumns: '80px 320px 1fr',
            gap: 40,
            padding: '32px 0',
            borderTop: i === 0 ? `1px solid rgba(10,11,16,0.1)` : undefined,
            borderBottom: `1px solid rgba(10,11,16,0.1)`,
            alignItems: 'start',
          }}>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 26,
              color: COLORS.blue, letterSpacing: '0.1em',
            }}>{n}</div>
            <div style={{
              fontFamily: FONTS.display, fontSize: 28,
              fontWeight: 900, textTransform: 'uppercase',
              color: COLORS.ink, lineHeight: 1.1,
            }}>{title}</div>
            <div style={{
              fontSize: 22, color: COLORS.muted, lineHeight: 1.45,
            }}>{desc}</div>
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 09 · STATUS  (dark)
// What's shipping + roadmap
// ─────────────────────────────────────────────────────────────
function N09Status() {
  const shipping = [
    ['gecko_classify + gecko_research + gecko_ask', 'LIVE'],
    ['x402 stub payments (Solana devnet)', 'LIVE'],
    ['Session persistence + 90-day context', 'LIVE'],
    ['Verdict hash + citation export', 'LIVE'],
    ['x402 mainnet settlement', 'POST-PILOT'],
    ['External contributor panel (open judging)', 'POST-PILOT'],
  ];
  const versions = [
    {
      v: 'V1',
      label: 'NOW',
      items: ['Claude Code MCP skill', 'Stub payments, devnet', '5 internal voices'],
    },
    {
      v: 'V1.5',
      label: '6 WEEKS',
      items: ['Mainnet USDC settlement', 'Pilot cohort (50 founders)', 'Verdict marketplace preview'],
    },
    {
      v: 'V2',
      label: '6 MONTHS',
      items: ['Open contributor panel', 'Reputation scores on-chain', 'Session-as-NFT export'],
    },
  ];
  return (
    <section data-label="Status" style={slideShell(true)}>
      <SlideHeader section="STATUS" page={9} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        width: 860,
      }}>
        <SlabTitle size={64} light>
          WHAT IS<br />
          <span style={{ color: COLORS.blue }}>SHIPPING.</span>
        </SlabTitle>

        {/* shipping list */}
        <div style={{ marginTop: 44, display: 'flex', flexDirection: 'column', gap: 0 }}>
          {shipping.map(([label, status]) => (
            <div key={label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '18px 0',
              borderBottom: `1px solid rgba(255,255,255,0.07)`,
              gap: 20,
            }}>
              <span style={{ fontSize: 22, color: 'rgba(255,255,255,0.8)', lineHeight: 1.3 }}>
                {label}
              </span>
              <Tag color={status === 'LIVE' ? 'blue' : 'black'} size={14}>
                {status}
              </Tag>
            </div>
          ))}
        </div>
      </div>

      {/* version stack */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        right: SPACING.paddingX,
        width: 580,
        display: 'flex',
        flexDirection: 'column',
        gap: 16,
      }}>
        {versions.map(({ v, label, items }) => (
          <div key={v} style={{
            background: 'rgba(30,86,245,0.07)',
            borderLeft: `3px solid ${COLORS.blue}`,
            padding: '24px 28px',
          }}>
            <div style={{ display: 'flex', gap: 18, alignItems: 'baseline', marginBottom: 14 }}>
              <span style={{
                fontFamily: FONTS.display, fontSize: 32, fontWeight: 900,
                color: COLORS.blue, textTransform: 'uppercase',
              }}>{v}</span>
              <span style={{
                fontFamily: FONTS.mono, fontSize: 14,
                letterSpacing: '0.14em', textTransform: 'uppercase',
                color: COLORS.blueDim,
              }}>{label}</span>
            </div>
            {items.map((it) => (
              <div key={it} style={{
                fontSize: 20, color: 'rgba(255,255,255,0.7)',
                lineHeight: 1.4, paddingLeft: 12,
              }}>· {it}</div>
            ))}
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 10 · ASK  (dark)
// ─────────────────────────────────────────────────────────────
function N10Ask() {
  const budget = [
    ['PRODUCT', '$120K', 'Core ML / prompt / eval harness'],
    ['GO-TO-MARKET', '$80K', '50-founder pilot, content, dev-community'],
    ['INFRA + OPS', '$50K', 'Supabase, Solana RPCs, audit, legal'],
  ];
  return (
    <section data-label="Ask" style={slideShell(true)}>
      <SlideHeader section="THE ASK" page={10} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 70,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <SlabTitle size={80} light>
          <span style={{ color: COLORS.blue }}>$250K</span>{' '}
          TO MAINNET<br />+ 50 FOUNDERS.
        </SlabTitle>
      </div>

      {/* budget rows */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 310,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        {budget.map(([category, amount, detail]) => (
          <div key={category} style={{
            display: 'grid',
            gridTemplateColumns: '240px 140px 1fr',
            gap: 32,
            padding: '24px 0',
            borderBottom: `1px solid rgba(255,255,255,0.07)`,
            alignItems: 'center',
          }}>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 18,
              letterSpacing: '0.12em', textTransform: 'uppercase',
              color: COLORS.blueDim,
            }}>{category}</div>
            <div style={{
              fontFamily: FONTS.display, fontSize: 36,
              fontWeight: 900, color: COLORS.white,
              textTransform: 'uppercase',
            }}>{amount}</div>
            <div style={{ fontSize: 22, color: 'rgba(255,255,255,0.55)', lineHeight: 1.3 }}>
              {detail}
            </div>
          </div>
        ))}
      </div>

      {/* founders block */}
      <div style={{
        position: 'absolute',
        bottom: 220,
        left: SPACING.paddingX,
        display: 'flex', gap: 60, alignItems: 'flex-start',
      }}>
        {[
          { name: 'ERNANI BRITTO', title: 'Product · Gecko', sub: 'prev: Superteam Brasil' },
          { name: 'LETICIA ALMEIDA', title: 'ML · Gecko', sub: 'prev: AI Research' },
        ].map(({ name, title, sub }) => (
          <div key={name}>
            <div style={{
              width: 72, height: 72, marginBottom: 16,
              background: 'rgba(30,86,245,0.18)',
              border: `1px solid ${COLORS.blue}`,
            }} />
            <div style={{
              fontFamily: FONTS.display, fontSize: 22,
              fontWeight: 900, textTransform: 'uppercase',
              color: COLORS.white,
            }}>{name}</div>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 16,
              letterSpacing: '0.08em', textTransform: 'uppercase',
              color: COLORS.blue, marginTop: 6,
            }}>{title}</div>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 14,
              letterSpacing: '0.06em', textTransform: 'uppercase',
              color: COLORS.muted, marginTop: 4,
            }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* closing line */}
      <div style={{
        position: 'absolute',
        bottom: 110,
        left: SPACING.paddingX, right: SPACING.paddingX,
        fontFamily: FONTS.display, fontSize: 30,
        fontWeight: 900, textTransform: 'uppercase',
        color: COLORS.white,
        letterSpacing: '-0.01em',
      }}>
        THE NEXT FOUNDER{' '}
        <span style={{ color: COLORS.blue }}>DOESN'T HAVE TO BUILD IN THE DARK.</span>
      </div>

      <SlideFooter dark />
    </section>
  );
}

Object.assign(window, {
  N01Thesis, N02Caio, N03DarkRoom, N04Shift, N05Product,
  N06Evidence, N07WhyNow, N08Moat, N09Status, N10Ask,
});
