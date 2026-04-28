// Builder Bootstrap deck — 8 slides
// Reuses common.jsx tokens & components

const bbShell = (dark) => ({
  background: dark ? COLORS.dark : COLORS.light,
  width: '100%', height: '100%',
  position: 'relative', overflow: 'hidden',
  fontFamily: FONTS.body,
  color: dark ? COLORS.white : COLORS.ink,
});

// 01 · COVER
function BB01Cover() {
  return (
    <section data-screen-label="01 Cover" data-om-validate style={bbShell(true)}>
      <div style={{
        position: 'absolute', top: 80, left: 0, right: 0,
        display: 'flex', justifyContent: 'center',
      }}>
        <GeckoLogo light size={52} />
      </div>

      <div style={{
        position: 'absolute', top: '46%', left: 0, right: 0,
        transform: 'translateY(-50%)',
        textAlign: 'center', padding: `0 ${SPACING.paddingX}px`,
      }}>
        <div style={{ marginBottom: 28 }}>
          <Tag color="blue">BUILDER BOOTSTRAP · POWERED BY x402</Tag>
        </div>
        <SlabTitle size={108} light>
          AN AI AGENT JUST PAID<br/>
          <span style={{ color: COLORS.blue }}>FOR ITS FOUNDER</span><br/>
          TO FIND OUT IF<br/>THE IDEA IS REAL.
        </SlabTitle>
        <div style={{
          marginTop: 32, fontFamily: FONTS.body, fontSize: 26,
          color: 'rgba(255,255,255,0.78)', maxWidth: 1200,
          marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.35,
        }}>
          The first product where an AI agent commissions startup<br/>
          validation for the founder it works for.
        </div>
        <div style={{
          marginTop: 32, fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono,
          letterSpacing: '0.14em', color: COLORS.blueDim, textTransform: 'uppercase',
        }}>
          GECKO PROTOCOL · COLOSSEUM · 2026
        </div>
      </div>

      <div style={{
        position: 'absolute', bottom: 80, left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
        fontFamily: FONTS.mono, fontSize: 20,
        color: 'rgba(255,255,255,0.6)', letterSpacing: '0.1em',
        textTransform: 'uppercase', whiteSpace: 'nowrap',
      }}>
        <div>
          <div style={{ color: COLORS.white, marginBottom: 6 }}>ERNANI BRITTO · CO-FOUNDER</div>
          <div>geckovision.tech</div>
        </div>
        <div style={{ color: COLORS.blueDim, textAlign: 'right' }}>
          SOLANA · DEVNET LIVE
        </div>
      </div>
    </section>
  );
}

// 02 · PROBLEM
function BB02Problem() {
  return (
    <section data-screen-label="02 Problem" data-om-validate style={bbShell(false)}>
      <SlideHeader section="THE PROBLEM" page={2} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle size={84}>
          FOUNDERS WASTE<br/>
          <span style={{ color: COLORS.blue }}>SIX MONTHS</span><br/>
          BUILDING THE WRONG THING.
        </SlabTitle>
      </div>

      <div style={{
        position: 'absolute', bottom: 220,
        left: SPACING.paddingX, right: SPACING.paddingX,
        maxWidth: 1500,
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 38, lineHeight: 1.25,
          color: COLORS.ink, letterSpacing: '-0.01em', textWrap: 'balance',
          marginBottom: 24,
        }}>
          "I spent <span style={{ color: COLORS.blue }}>twenty hours</span> manually transcribing
          YouTube videos before I knew if my idea was real. Then I shipped the wrong product
          and lost six months."
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono,
          color: COLORS.muted, letterSpacing: '0.12em', textTransform: 'uppercase',
        }}>
          — ERNANI · CO-FOUNDER, GECKO
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// 03 · PRODUCT
function BB03Product() {
  const docs = [
    ['BUSINESS PLAN', 'Problem · market · positioning · 90-day plan.'],
    ['VALIDATION REPORT', 'Demand signals · competitors · risks · go/no-go.'],
    ['PRD', 'Scope · users · MVP cuts · success metrics.'],
  ];
  return (
    <section data-screen-label="03 Product" data-om-validate style={bbShell(true)}>
      <SlideHeader section="THE PRODUCT" page={3} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <Tag color="blue">30 MIN. NOT 20 HOURS.</Tag>
        <div style={{ marginTop: 22 }}>
          <SlabTitle light size={84}>
            FROM IDEA TO<br/>
            <span style={{ color: COLORS.blue }}>VALIDATED DECISION,</span><br/>
            EVERY CLAIM CITED.
          </SlabTitle>
        </div>
      </div>

      <div style={{
        position: 'absolute', bottom: 200,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28,
      }}>
        {docs.map(([t, d]) => (
          <div key={t} style={{
            border: '1px solid rgba(184,199,249,0.25)',
            background: 'rgba(30,86,245,0.06)',
            padding: '28px 28px 32px',
            minHeight: 230, display: 'flex', flexDirection: 'column',
          }}>
            <Tag color="blue" size={TYPE_SCALE.tag}>{t}</Tag>
            <div style={{
              marginTop: 22, fontSize: 24, lineHeight: 1.4,
              color: 'rgba(255,255,255,0.82)',
            }}>{d}</div>
            <div style={{
              marginTop: 'auto', paddingTop: 24,
              fontFamily: FONTS.mono, fontSize: 18,
              color: COLORS.blueDim, letterSpacing: '0.1em', textTransform: 'uppercase',
            }}>
              CITATIONS · 7+ SOURCES
            </div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// 04 · WHY x402
function BB04WhyX402() {
  const reasons = [
    ['THE BUYER IS AN AGENT', "Agents can't use Stripe. Can't fill forms. x402 is the only standard a machine can pay through autonomously."],
    ['NO API KEYS, EVER', 'Wallet signature is auth. The same primitive does payment. Removing x402 means re-introducing humans.'],
    ['THE STACK COMPOSES', 'frames.ag, ClawRouter, and Gecko interop because they all speak x402. Without it, no composition.'],
  ];
  return (
    <section data-screen-label="04 Why x402" data-om-validate style={bbShell(false)}>
      <SlideHeader section="WHY x402" page={4} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle size={80}>
          x402 ISN'T CHECKOUT.<br/>
          <span style={{ color: COLORS.blue }}>IT'S STRUCTURAL.</span>
        </SlabTitle>
      </div>

      <div style={{
        position: 'absolute', bottom: 200,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'flex', flexDirection: 'column', gap: 18,
      }}>
        {reasons.map(([t, d], i) => (
          <div key={t} style={{
            background: COLORS.white,
            border: '1px solid rgba(10,11,16,0.08)',
            padding: '22px 28px',
            display: 'grid', gridTemplateColumns: '80px 360px 1fr', alignItems: 'center', gap: 28,
            position: 'relative',
          }}>
            <div style={{
              position: 'absolute', top: 0, left: 0, bottom: 0, width: 3, background: COLORS.blue,
            }} />
            <div style={{
              fontFamily: FONTS.mono, fontSize: 18, color: COLORS.blue,
              letterSpacing: '0.1em',
            }}>0{i+1}</div>
            <div style={{
              fontFamily: FONTS.display, fontSize: 26, color: COLORS.ink,
              letterSpacing: '-0.01em', textTransform: 'uppercase',
            }}>{t}</div>
            <div style={{
              fontSize: 22, color: COLORS.muted, lineHeight: 1.35,
            }}>{d}</div>
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

// 05 · ARCHITECTURE
function BB05Architecture() {
  const boxes = [
    ['BUILDER\'S AGENT', 'frames.ag wallet', 'Pays Gecko'],
    ['GECKO API', 'x402 middleware', 'Verifies + runs'],
    ['LLM PROVIDERS', 'ClawRouter', 'Routes + pays'],
  ];
  return (
    <section data-screen-label="05 Architecture" data-om-validate style={bbShell(true)}>
      <SlideHeader section="ARCHITECTURE" page={5} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle light size={80}>
          EVERY PAYMENT IN<br/>
          THE STACK IS <span style={{ color: COLORS.blue }}>x402.</span>
        </SlabTitle>
      </div>

      <div style={{
        position: 'absolute', top: 460,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid', gridTemplateColumns: '1fr 60px 1fr 60px 1fr', alignItems: 'center', gap: 0,
      }}>
        {boxes.map(([t, m, d], i) => (
          <React.Fragment key={t}>
            <div style={{
              border: '1px solid rgba(184,199,249,0.3)',
              background: 'rgba(30,86,245,0.08)',
              padding: '32px 28px', minHeight: 220,
              display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
            }}>
              <div style={{
                fontFamily: FONTS.display, fontSize: 28, color: COLORS.white,
                letterSpacing: '-0.01em', textTransform: 'uppercase', lineHeight: 1.1,
              }}>{t}</div>
              <div>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 18, color: COLORS.blueDim,
                  letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6,
                }}>{m}</div>
                <div style={{ fontSize: 20, color: 'rgba(255,255,255,0.75)' }}>{d}</div>
              </div>
            </div>
            {i < 2 && (
              <div style={{
                fontFamily: FONTS.display, fontSize: 56, color: COLORS.blue,
                textAlign: 'center', lineHeight: 1,
              }}>→</div>
            )}
          </React.Fragment>
        ))}
      </div>

      <div style={{
        position: 'absolute', bottom: 160,
        left: SPACING.paddingX, right: SPACING.paddingX,
        textAlign: 'center', borderTop: '1px solid rgba(184,199,249,0.2)', paddingTop: 22,
        fontFamily: FONTS.mono, fontSize: 22, color: COLORS.blueDim,
        letterSpacing: '0.14em', textTransform: 'uppercase',
      }}>
        ALL USDC · ALL ON-CHAIN · ALL VISIBLE — NO API KEYS, ANYWHERE
      </div>

      <SlideFooter dark />
    </section>
  );
}

// 06 · STATUS
function BB06Status() {
  const rows = [
    ['Core SDK + ingestion + RAG', 'LIVE', 'green'],
    ['x402 payment middleware on gecko-api', 'LIVE', 'green'],
    ['frames.ag wallet integration', 'LIVE', 'green'],
    ['ClawRouter LLM integration', 'LIVE', 'green'],
    ['MCP server + Claude Code skill', 'LIVE', 'green'],
    ['Solana devnet transactions', 'TESTING', 'blue'],
    ['Pro tier · 5-agent GroupChat', 'IN PROGRESS', 'amber'],
    ['Solana mainnet · audited deploy', 'POST-TEST', 'muted'],
  ];
  const dotColor = (k) => k === 'green' ? COLORS.green
    : k === 'blue' ? COLORS.blue
    : k === 'amber' ? '#F4B860'
    : 'rgba(10,11,16,0.25)';
  return (
    <section data-screen-label="06 Status" data-om-validate style={bbShell(false)}>
      <SlideHeader section="STATUS" page={6} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle size={80}>
          WORKING TODAY,<br/>
          <span style={{ color: COLORS.blue }}>ON SOLANA DEVNET.</span>
        </SlabTitle>
        <p style={{
          marginTop: 22, fontSize: 24, color: COLORS.muted, lineHeight: 1.35, maxWidth: 1100,
        }}>
          We test before mainnet — same code path, same flow, real x402 transactions.
        </p>
      </div>

      <div style={{
        position: 'absolute', bottom: 180,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'flex', flexDirection: 'column',
        borderTop: `1px solid ${COLORS.ink}`,
      }}>
        {rows.map(([label, state, kind]) => (
          <div key={label} style={{
            display: 'grid', gridTemplateColumns: '24px 1fr 200px',
            alignItems: 'center', padding: '16px 0', gap: 20,
            borderBottom: '1px solid rgba(10,11,16,0.08)',
          }}>
            <div style={{
              width: 14, height: 14, borderRadius: '50%', background: dotColor(kind),
            }} />
            <div style={{ fontSize: 24, color: COLORS.ink }}>{label}</div>
            <div style={{ textAlign: 'right' }}>
              <Tag color={kind === 'green' ? 'blue' : 'black'} size={15}>{state}</Tag>
            </div>
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

// 07 · ROADMAP
function BB07Roadmap() {
  const phases = [
    ['V1', 'NOW', 'Devnet test · founder pilots', 'Builder Bootstrap. Paid research sessions. Pro tier rolls out.'],
    ['V1.5', 'Q3 2026', 'Mainnet after audit', '5-agent GroupChat live. First brand partner integrations.'],
    ['V2', '2027', 'Knowledge API', 'Validation → due diligence → market sizing. Same rails, new categories.'],
  ];
  return (
    <section data-screen-label="07 Roadmap" data-om-validate style={bbShell(true)}>
      <SlideHeader section="ROADMAP" page={7} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle light size={80}>
          SESSIONS TODAY.<br/>
          <span style={{ color: COLORS.blue }}>KNOWLEDGE MARKETPLACE</span> TOMORROW.
        </SlabTitle>
      </div>

      <div style={{
        position: 'absolute', bottom: 200,
        left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28,
      }}>
        {phases.map(([v, when, head, body], i) => (
          <div key={v} style={{
            background: i === 0 ? 'rgba(30,86,245,0.12)' : 'rgba(184,199,249,0.04)',
            border: `1px solid ${i === 0 ? COLORS.blue : 'rgba(184,199,249,0.2)'}`,
            padding: '28px', minHeight: 280,
            display: 'flex', flexDirection: 'column',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 18 }}>
              <span style={{
                fontFamily: FONTS.display, fontSize: 56, color: COLORS.white,
                letterSpacing: '-0.02em',
              }}>{v}</span>
              <Tag color={i === 0 ? 'blue' : 'black'} size={15}>{when}</Tag>
            </div>
            <div style={{
              fontFamily: FONTS.display, fontSize: 24, color: COLORS.white,
              letterSpacing: '-0.01em', textTransform: 'uppercase', marginBottom: 14,
            }}>{head}</div>
            <div style={{
              fontSize: 20, lineHeight: 1.4, color: 'rgba(255,255,255,0.72)',
            }}>{body}</div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// 08 · ASK
function BB08Ask() {
  return (
    <section data-screen-label="08 Ask" data-om-validate style={bbShell(true)}>
      <SlideHeader section="THE ASK" page={8} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, width: 980,
      }}>
        <SlabTitle light size={84}>
          WE WANT A<br/>
          <span style={{ color: COLORS.blue }}>COLOSSEUM</span><br/>
          ACCELERATOR SLOT.
        </SlabTitle>

        <div style={{ marginTop: 48, display: 'flex', flexDirection: 'column', gap: 14 }}>
          {[
            ['$250K', 'Pre-seed funding · 12 months runway'],
            ['MENTORS', 'Network in agentic infrastructure'],
            ['CREDIBILITY', 'Stamp opens x402 ecosystem doors'],
          ].map(([k, v]) => (
            <div key={k} style={{
              display: 'flex', alignItems: 'center', gap: 20,
              padding: '14px 22px',
              background: 'rgba(30,86,245,0.08)',
              borderLeft: `3px solid ${COLORS.blue}`,
            }}>
              <span style={{
                fontFamily: FONTS.display, fontSize: 28, color: COLORS.blue,
                minWidth: 180,
              }}>{k}</span>
              <span style={{ fontSize: 22, color: COLORS.white }}>{v}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 80,
        right: SPACING.paddingX, width: 560,
      }}>
        <Tag color="blue">FOUNDERS</Tag>
        <div style={{
          marginTop: 22,
          fontFamily: FONTS.display, fontSize: 36, color: COLORS.white,
          letterSpacing: '-0.01em', lineHeight: 1.15,
        }}>
          ERNANI BRITTO
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 18, color: COLORS.blueDim,
          letterSpacing: '0.1em', textTransform: 'uppercase', marginTop: 8,
        }}>15+ YRS ENG · LIVED THE PAIN TWICE</div>

        <div style={{ marginTop: 24,
          fontFamily: FONTS.display, fontSize: 36, color: COLORS.white,
          letterSpacing: '-0.01em', lineHeight: 1.15,
        }}>
          + CO-FOUNDER · DESIGN
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 18, color: COLORS.blueDim,
          letterSpacing: '0.1em', textTransform: 'uppercase', marginTop: 8,
        }}>SUPERTEAMBR · BRAZIL</div>

        <div style={{ marginTop: 40, padding: '20px 22px',
          background: COLORS.white, color: COLORS.ink,
        }}>
          <div style={{
            fontFamily: FONTS.mono, fontSize: 16, color: COLORS.blue,
            letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 8,
          }}>INSTALL · ONE URL</div>
          <div style={{
            fontFamily: FONTS.mono, fontSize: 20, color: COLORS.ink, wordBreak: 'break-all',
          }}>
            app.geckovision.tech/<br/>skill.md
          </div>
        </div>
      </div>

      <div style={{
        position: 'absolute', bottom: 110,
        left: SPACING.paddingX, right: 700, textAlign: 'left',
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 26, color: COLORS.white,
          letterSpacing: '-0.01em', textTransform: 'uppercase', lineHeight: 1.2, marginBottom: 12,
        }}>
          IF YOU'VE EVER WASTED SIX MONTHS BUILDING THE WRONG THING —<br/>
          <span style={{ color: COLORS.blue }}>GECKO EXISTS SO THE NEXT FOUNDER DOESN'T HAVE TO.</span>
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 18, color: COLORS.blueDim,
          letterSpacing: '0.14em', textTransform: 'uppercase',
        }}>
          ERNANI@GECKOVISION.TECH · GECKOVISION.TECH · GITHUB.COM/GECKO
        </div>
      </div>

      <SlideFooter dark />
    </section>
  );
}

Object.assign(window, {
  BB01Cover, BB02Problem, BB03Product, BB04WhyX402,
  BB05Architecture, BB06Status, BB07Roadmap, BB08Ask,
});
