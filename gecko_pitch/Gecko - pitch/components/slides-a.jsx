// Gecko deck — Slides 1-4
// 1: Cover, 2: Problem, 3: Reframe (transparency vs enforcement), 4: How it works

const slideShell = (dark) => ({
  background: dark ? COLORS.dark : COLORS.light,
  width: '100%', height: '100%',
  position: 'relative', overflow: 'hidden',
  fontFamily: FONTS.body,
  color: dark ? COLORS.white : COLORS.ink,
});

// ─────────────────────────────────────────────────────────────
// 01 · COVER
// ─────────────────────────────────────────────────────────────
function Slide01Cover() {
  return (
    <section data-label="Cover" style={slideShell(true)}>
      {/* dark textured background with glitch dots */}
      <div style={{
        position: 'absolute', inset: 0,
        background: `radial-gradient(ellipse at 70% 30%, rgba(30,86,245,0.18), transparent 55%),
                     radial-gradient(ellipse at 20% 80%, rgba(30,86,245,0.10), transparent 50%)`,
      }} />
      {/* scattered squares */}
      {[[120,180,14],[240,120,8],[1680,240,12],[1760,360,8],[180,820,16],[320,920,8],
        [1540,820,10],[1720,880,14],[1820,640,8],[80,460,8],[1820,180,8]].map(([x,y,s],i)=>(
        <div key={i} style={{
          position: 'absolute', left: x, top: y, width: s, height: s,
          background: `rgba(30,86,245,${0.25 + (i%3)*0.15})`,
        }} />
      ))}

      {/* centered logo top */}
      <div style={{
        position: 'absolute', top: 80, left: 0, right: 0,
        display: 'flex', justifyContent: 'center',
      }}>
        <GeckoLogo light size={52} />
      </div>

      {/* centered title block */}
      <div style={{
        position: 'absolute', top: '44%', left: 0, right: 0,
        transform: 'translateY(-50%)',
        textAlign: 'center', padding: `0 ${SPACING.paddingX}px`,
      }}>
        <div style={{ marginBottom: 28 }}>
          <Tag color="blue" size={TYPE_SCALE.tag}>ORACLE-FIRST CAMPAIGN ESCROW ON SOLANA</Tag>
        </div>
        <SlabTitle size={108} light>
          THE BRAND<br/>CANNOT CANCEL.<br/>
          <span style={{ color: COLORS.blue }}>THE CODE SAYS SO.</span>
        </SlabTitle>
        <div style={{
          marginTop: 28,
          fontFamily: FONTS.body, fontSize: 26,
          color: 'rgba(255,255,255,0.78)', lineHeight: 1.35,
          maxWidth: 1200, marginLeft: 'auto', marginRight: 'auto',
        }}>
          Onchain campaign escrow that auto-releases creator payouts<br/>
          when milestones hit — no brand override, no disputes.
        </div>
        <div style={{
          marginTop: 28, fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono,
          letterSpacing: '0.14em', color: COLORS.blueDim, textTransform: 'uppercase',
        }}>
          GECKO PROTOCOL · COLOSSEUM FRONTIER · 2026
        </div>
      </div>

      {/* bottom row: presenters */}
      <div style={{
        position: 'absolute', bottom: 80, left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
        color: 'rgba(255,255,255,0.6)', letterSpacing: '0.1em', textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}>
        <div>
          <div style={{ color: COLORS.white, marginBottom: 6 }}>ERNANI BRITTO · LETICIA ALMEIDA</div>
          <div>geckovision.tech</div>
        </div>
        <div style={{ textAlign: 'right', color: COLORS.blueDim }}>
          SEED · $250K
        </div>
      </div>
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 02 · PROBLEM
// ─────────────────────────────────────────────────────────────
function Slide02Problem() {
  return (
    <section data-label="Problem" style={slideShell(false)}>
      <SlideHeader section="PROBLEM" page={2} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX,
        width: 880,
      }}>
        <SlabTitle size={72}>
          CREATOR MARKETING<br/>BREAKS AT THE<br/>
          <span style={{ color: COLORS.blue }}>MOMENT OF COMMITMENT</span>
        </SlabTitle>
        <p style={{
          marginTop: 28, marginBottom: 0,
          fontSize: 28, lineHeight: 1.35, color: COLORS.muted,
          maxWidth: 780,
        }}>
          Today's campaigns still run on emails, PDFs, manual approvals,
          and post-hoc negotiation.
        </p>

        {/* three pain points, each with a tag */}
        <div style={{ marginTop: 40, display: 'flex', flexDirection: 'column', gap: 20 }}>
          {[
            ['BRANDS GHOST', 'Delay, renegotiate, or disappear after content ships.'],
            ['CREATORS UNDERDELIVER', 'Budget commits with no enforceable execution logic.'],
            ['CONTRACTS TOO SMALL TO SUE', 'Below legal threshold — trust replaces infrastructure.'],
          ].map(([tag, desc]) => (
            <div key={tag} style={{ display: 'flex', alignItems: 'flex-start', gap: 20 }}>
              <div style={{ paddingTop: 4, minWidth: 360 }}><Tag>{tag}</Tag></div>
              <div style={{ fontSize: 24, lineHeight: 1.3, color: COLORS.ink, flex: 1 }}>
                {desc}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* right: big stat card */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 100,
        right: SPACING.paddingX,
        width: 560,
      }}>
        <PhotoCard label="CREATOR / BRAND FRICTION" width={520} height={540} />
        <div style={{
          position: 'absolute', bottom: -30, left: 40,
          zIndex: 2,
        }}>
          <Tag color="black" size={TYPE_SCALE.tag}>92% OF DISPUTES FAVOR LEVERAGE</Tag>
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 03 · REFRAME — Transparency ≠ Enforcement
// ─────────────────────────────────────────────────────────────
function Slide03Reframe() {
  const rows = [
    ['Show status in a dashboard', 'Lock commitment in code'],
    ['Add a middleman', 'Enforce release onchain'],
    ['Track payment manually', 'Tie payout to conditions'],
    ['Rely on support teams', 'Rely on program rules'],
  ];
  return (
    <section data-label="Reframe" style={slideShell(false)}>
      <SlideHeader section="THESIS" page={3} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
        width: 900,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 24, flexWrap: 'wrap' }}>
          <SlabTitle size={68} style={{ color: COLORS.muted }}>
            THIS IS NOT A<br/>TRANSPARENCY PROBLEM.
          </SlabTitle>
        </div>
        <SlabTitle size={92} style={{ marginTop: 12 }}>
          IT IS AN<br/>
          <span style={{ color: COLORS.blue }}>ENFORCEABILITY</span><br/>PROBLEM.
        </SlabTitle>
      </div>

      {/* Right side: comparison table */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 180,
        right: SPACING.paddingX,
        width: 720,
      }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '1fr 1fr',
          borderTop: `1px solid ${COLORS.ink}`,
        }}>
          <div style={{
            padding: '14px 0',
            fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
            letterSpacing: '0.12em', textTransform: 'uppercase',
            color: COLORS.muted,
          }}>MOST TOOLS</div>
          <div style={{
            padding: '14px 0',
            fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
            letterSpacing: '0.12em', textTransform: 'uppercase',
            color: COLORS.blue,
          }}>GECKO</div>

          {rows.map(([l, r], i) => (
            <React.Fragment key={i}>
              <div style={{
                padding: '22px 24px 22px 0',
                borderTop: `1px solid rgba(10,11,16,0.12)`,
                fontSize: TYPE_SCALE.body - 2, color: COLORS.muted,
                lineHeight: 1.25,
              }}>{l}</div>
              <div style={{
                padding: '22px 0',
                borderTop: `1px solid rgba(10,11,16,0.12)`,
                fontSize: TYPE_SCALE.body - 2, color: COLORS.ink, fontWeight: 600,
                lineHeight: 1.25,
              }}>{r}</div>
            </React.Fragment>
          ))}
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 04 · HOW IT WORKS (5 ops)
// ─────────────────────────────────────────────────────────────
function Slide04HowItWorks() {
  const steps = [
    ['01', 'DEPOSIT', 'Brand locks USDC into a campaign vault.'],
    ['02', 'ALLOCATE', 'Creators are added with fixed weights.'],
    ['03', 'LAUNCH', '10% advance auto-released on go-live.'],
    ['04', 'MILESTONES', 'Oracle scores unlock tranche releases.'],
    ['05', 'CLOSE', 'Cliff hits. Unused funds return to brand.'],
  ];
  return (
    <section data-label="Product" style={slideShell(false)}>
      <SlideHeader section="PRODUCT" page={4} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX,
        right: SPACING.paddingX,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18, marginBottom: 22 }}>
          <Tag color="blue" size={TYPE_SCALE.tag}>● LIVE ON SOLANA DEVNET</Tag>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 18, letterSpacing: '0.1em',
            color: COLORS.muted, textTransform: 'uppercase',
          }}>VAULT LIFECYCLE · ADVANCE · ALLOCATION · ORACLE PIPELINE</span>
        </div>
        <SlabTitle>
          A CAMPAIGN AS<br/>
          <span style={{ color: COLORS.blue }}>FIVE ENFORCEABLE</span> OPERATIONS
        </SlabTitle>
      </div>

      {/* 5-step horizontal flow */}
      <div style={{
        position: 'absolute',
        bottom: 180, left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 20,
      }}>
        {steps.map(([n, title, desc], i) => (
          <div key={n} style={{
            background: COLORS.white,
            border: `1px solid rgba(10,11,16,0.1)`,
            padding: '30px 26px 28px',
            position: 'relative', minHeight: 280,
            display: 'flex', flexDirection: 'column',
          }}>
            {/* blue accent bar top */}
            <div style={{
              position: 'absolute', top: 0, left: 0, height: 4, width: 44,
              background: COLORS.blue,
            }} />
            <div style={{
              fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono,
              color: COLORS.blue, letterSpacing: '0.1em', marginBottom: 18,
            }}>{n}</div>
            <div style={{
              fontFamily: FONTS.display, fontSize: 34, letterSpacing: '-0.01em',
              textTransform: 'uppercase', color: COLORS.ink, marginBottom: 14, lineHeight: 1,
            }}>
              {title}
            </div>
            <div style={{
              fontSize: TYPE_SCALE.small, color: COLORS.muted, lineHeight: 1.3,
              marginTop: 'auto',
            }}>
              {desc}
            </div>
            {/* arrow connector (except last) */}
            {i < steps.length - 1 && (
              <div style={{
                position: 'absolute', top: '50%', right: -18,
                transform: 'translateY(-50%)', zIndex: 2,
                color: COLORS.blue, fontSize: 24, fontWeight: 300,
              }}>→</div>
            )}
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

Object.assign(window, {
  Slide01Cover, Slide02Problem, Slide03Reframe, Slide04HowItWorks,
});
