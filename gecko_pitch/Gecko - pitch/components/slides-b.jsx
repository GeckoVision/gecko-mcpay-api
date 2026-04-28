// Gecko deck — Slides 5-8
// 5: Why Solana, 6: Market + GTM, 7: Competition, 8: Team + Ask

const slideShellB = (dark) => ({
  background: dark ? COLORS.dark : COLORS.light,
  width: '100%', height: '100%',
  position: 'relative', overflow: 'hidden',
  fontFamily: FONTS.body,
  color: dark ? COLORS.white : COLORS.ink,
});

// ─────────────────────────────────────────────────────────────
// 05 · WHY SOLANA — capability-led reframe
// ─────────────────────────────────────────────────────────────
function Slide05WhySolana() {
  const pillars = [
    {
      tag: 'NET-ZERO',
      headline: 'From Net-60 to Net-0',
      desc: 'Creators get paid the instant conditions hit. 400ms settlement kills payment terms.',
    },
    {
      tag: 'CONTINUOUS',
      headline: 'Verified hourly, not at payout',
      desc: 'On Ethereum, one oracle check costs more than the milestone. On Solana, we check constantly.',
    },
    {
      tag: 'SELF-ENFORCING',
      headline: 'The deal runs itself',
      desc: 'Vaults, splits, and deadlines live in code. No lawyer, no escrow agent, no human in the loop.',
    },
  ];
  return (
    <section data-label="Why Solana" style={slideShellB(true)}>
      <SlideHeader section="WHY SOLANA" page={5} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle light>
          CAMPAIGNS THAT<br/>
          <span style={{ color: COLORS.blue }}>RUN THEMSELVES.</span><br/>
          ONLY POSSIBLE ON SOLANA.
        </SlabTitle>
      </div>

      <div style={{
        position: 'absolute',
        bottom: 200, left: SPACING.paddingX, right: SPACING.paddingX,
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 28,
      }}>
        {pillars.map(p => (
          <div key={p.tag} style={{
            border: '1px solid rgba(184,199,249,0.25)',
            background: 'rgba(30,86,245,0.06)',
            padding: '34px 32px',
            minHeight: 280,
            display: 'flex', flexDirection: 'column',
          }}>
            <Tag color="blue" size={TYPE_SCALE.tag}>{p.tag}</Tag>
            <div style={{
              fontFamily: FONTS.display, fontSize: 40, color: COLORS.white,
              letterSpacing: '-0.02em', marginTop: 24, marginBottom: 18, lineHeight: 1.05,
              textTransform: 'uppercase',
            }}>
              {p.headline}
            </div>
            <div style={{
              fontSize: TYPE_SCALE.small, color: 'rgba(255,255,255,0.72)',
              lineHeight: 1.4, marginTop: 'auto',
            }}>
              {p.desc}
            </div>
          </div>
        ))}
      </div>

      <SlideFooter dark />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 06 · MARKET + GTM
// ─────────────────────────────────────────────────────────────
function Slide06Market() {
  return (
    <section data-label="Market" style={slideShellB(false)}>
      <SlideHeader section="MARKET · GTM" page={6} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX,
        width: 820,
      }}>
        <SlabTitle>
          $21B MARKET.<br/>
          WE START WHERE<br/>
          <span style={{ color: COLORS.blue }}>ENFORCEMENT ALREADY HURTS.</span>
        </SlabTitle>

        {/* TAM SAM SOM */}
        <div style={{ marginTop: 56, display: 'flex', flexDirection: 'column', gap: 22 }}>
          {[
            ['TAM', '$21B', 'Global influencer marketing · 2025', 1.0],
            ['SAM', '$4.2B', 'Mid-market, enforcement-critical', 0.5],
            ['SOM', '$42M', 'Protocol fee on locked TVL · Year 1', 0.15],
          ].map(([label, val, desc, w]) => (
            <div key={label}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, marginBottom: 8 }}>
                <div style={{ width: 70 }}><Tag>{label}</Tag></div>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 18,
                  color: COLORS.muted, letterSpacing: '0.08em', textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                }}>{desc}</div>
              </div>
              <div style={{
                height: 44, position: 'relative',
                background: 'rgba(10,11,16,0.05)',
              }}>
                <div style={{
                  position: 'absolute', top: 0, left: 0, bottom: 0,
                  width: `${w * 100}%`, background: COLORS.blue,
                }} />
                <div style={{
                  position: 'absolute', left: 16, top: 0, bottom: 0,
                  display: 'flex', alignItems: 'center',
                  fontFamily: FONTS.display, fontSize: 28, color: COLORS.white,
                  letterSpacing: '-0.01em',
                }}>{val}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Right: wedge ICPs */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        right: SPACING.paddingX,
        width: 660,
      }}>
        <div style={{
          fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
          letterSpacing: '0.14em', textTransform: 'uppercase',
          color: COLORS.blue, marginBottom: 22,
        }}>
          WAVE 1 · WEDGE ICPs
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {[
            ['01', 'TREXX', 'LATAM esports · 16+ teams. SDK integration.', '1 deal = 16 rosters'],
            ['02', 'SOLANA GAMING STUDIOS', 'Aurory · Star Atlas · Nyan Heroes · Stepn', '$5K–$100K / campaign'],
          ].map(([n, name, desc, vol]) => (
            <div key={n} style={{
              background: COLORS.white,
              border: '1px solid rgba(10,11,16,0.08)',
              padding: '22px 24px',
              position: 'relative',
            }}>
              <div style={{
                position: 'absolute', top: 0, left: 0, bottom: 0, width: 3,
                background: COLORS.blue,
              }} />
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 6 }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
                  color: COLORS.blue, letterSpacing: '0.1em',
                }}>#{n}</span>
                <span style={{
                  fontFamily: FONTS.display, fontSize: 28, letterSpacing: '-0.01em',
                  color: COLORS.ink,
                }}>{name}</span>
              </div>
              <div style={{ fontSize: 22, color: COLORS.muted, lineHeight: 1.3 }}>
                {desc}
              </div>
              <div style={{
                marginTop: 10,
                fontFamily: FONTS.mono, fontSize: 18,
                color: COLORS.ink, letterSpacing: '0.08em', textTransform: 'uppercase',
              }}>
                → {vol}
              </div>
            </div>
          ))}
        </div>
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 07 · COMPETITION
// ─────────────────────────────────────────────────────────────
function Slide07Competition() {
  const rows = [
    { name: 'TRADITIONAL AGENCIES', tag: 'Invoices · 15–25% take', threat: 'HIGH',
      cells: [false, false, false, false] },
    { name: 'DAISY PAY', tag: 'Solana payment rail', threat: 'MED',
      cells: [false, false, true, false] },
    { name: 'LUMANU', tag: 'Centralized SaaS · Off-chain', threat: 'HIGH',
      cells: [true, true, false, false] },
    { name: 'INFLUUR', tag: 'ETH marketplace', threat: 'MED',
      cells: [true, false, true, false] },
    { name: 'GECKO', tag: 'Solana protocol', threat: 'US',
      cells: [true, true, true, true], us: true },
  ];
  const cols = ['ESCROW', 'ORACLE MILESTONES', 'ONCHAIN SETTLEMENT', 'CLIFF · NO CANCEL'];
  return (
    <section data-label="Competition" style={slideShellB(false)}>
      <SlideHeader section="COMPETITION" page={7} />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 40,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle size={68}>
          EVERYONE ELSE CAN STILL<br/>
          <span style={{ color: COLORS.muted }}>CANCEL, DISPUTE, OR STALL.</span>
        </SlabTitle>
        <p style={{ marginTop: 20, fontSize: 26, color: COLORS.muted, lineHeight: 1.3, maxWidth: 1200 }}>
          Escrow is table stakes. The cliff — payout that can't be reversed once conditions hit — is the moat.
        </p>
      </div>

      {/* Matrix */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 260,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: '320px repeat(4, 1fr) 120px',
          fontFamily: FONTS.mono, fontSize: 16,
          letterSpacing: '0.08em', textTransform: 'uppercase',
          color: COLORS.muted,
          borderTop: `1px solid ${COLORS.ink}`,
          borderBottom: `1px solid rgba(10,11,16,0.15)`,
        }}>
          <div style={{ padding: '12px 0' }}></div>
          {cols.map(c => <div key={c} style={{ padding: '12px 10px', textAlign: 'center' }}>{c}</div>)}
          <div style={{ padding: '12px 0', textAlign: 'right' }}>THREAT</div>
        </div>

        {rows.map((r, i) => (
          <div key={r.name} style={{
            display: 'grid',
            gridTemplateColumns: '320px repeat(4, 1fr) 120px',
            borderBottom: `1px solid rgba(10,11,16,0.08)`,
            background: r.us ? 'rgba(30,86,245,0.08)' : 'transparent',
            alignItems: 'center',
          }}>
            <div style={{ padding: '16px 0' }}>
              <div style={{
                fontFamily: FONTS.display, fontSize: 24, letterSpacing: '-0.01em',
                color: r.us ? COLORS.blue : COLORS.ink,
              }}>{r.name}</div>
              <div style={{
                fontFamily: FONTS.mono, fontSize: 14,
                color: COLORS.muted, letterSpacing: '0.08em', textTransform: 'uppercase',
                marginTop: 4,
              }}>{r.tag}</div>
            </div>
            {r.cells.map((c, j) => (
              <div key={j} style={{
                padding: '16px 10px', textAlign: 'center',
                fontSize: 28,
                color: c ? (r.us ? COLORS.blue : COLORS.ink) : 'rgba(10,11,16,0.18)',
              }}>
                {c ? '●' : '○'}
              </div>
            ))}
            <div style={{ padding: '16px 0', textAlign: 'right' }}>
              <Tag color={r.us ? 'blue' : 'black'} size={14}>{r.threat}</Tag>
            </div>
          </div>
        ))}
      </div>

      <SlideFooter />
    </section>
  );
}

// ─────────────────────────────────────────────────────────────
// 08 · TEAM + ASK
// ─────────────────────────────────────────────────────────────
function Slide08TeamAsk() {
  return (
    <section data-label="Team and Ask" style={slideShellB(true)}>
      <SlideHeader section="TEAM · ASK" page={8} dark />

      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 60,
        left: SPACING.paddingX, right: SPACING.paddingX,
      }}>
        <SlabTitle light>
          BUILT BY BUILDERS WITH<br/>
          <span style={{ color: COLORS.blue }}>DIRECT LINE</span> TO THE WEDGE.
        </SlabTitle>
      </div>

      {/* Founders */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 300,
        left: SPACING.paddingX,
        width: 980,
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32,
      }}>
        {[
          {
            name: 'ERNANI BRITTO', role: 'ENG & INFRA',
            bullets: [
              'Built + scaled a no-code AI training tool with founding team.',
              'Former Santander & Itaú engineer.',
              'Ships validation, scoring, payout flows end-to-end.',
            ],
          },
          {
            name: 'LETICIA ALMEIDA', role: 'PRODUCT & OPS',
            bullets: [
              'Led open-innovation projects at Liga Ventures for BASF, Saint-Gobain, Sodexo, Mercedes-Benz.',
              'Admin of a high-trust Corinthians fan community → creator access at scale.',
              'Turns thesis into playbooks and pilot workflows.',
            ],
          },
        ].map(p => (
          <div key={p.name} style={{
            border: '1px solid rgba(184,199,249,0.2)',
            padding: '28px 28px 30px',
            background: 'rgba(30,86,245,0.04)',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
              <div style={{
                width: 56, height: 56, borderRadius: '50%',
                border: `2px solid ${COLORS.blue}`,
                background: 'rgba(30,86,245,0.15)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: FONTS.display, fontSize: 22, color: COLORS.white,
              }}>{p.name[0]}</div>
              <div>
                <div style={{
                  fontFamily: FONTS.display, fontSize: 28, letterSpacing: '-0.01em',
                  color: COLORS.white,
                }}>{p.name}</div>
                <Tag color="blue" size={15}>{p.role}</Tag>
              </div>
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 12 }}>
              {p.bullets.map((b, i) => (
                <li key={i} style={{
                  fontSize: 22, color: 'rgba(255,255,255,0.78)', lineHeight: 1.35,
                  display: 'flex', gap: 12,
                }}>
                  <span style={{ color: COLORS.blue, flexShrink: 0 }}>↗</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* The Ask */}
      <div style={{
        position: 'absolute',
        top: SPACING.paddingTop + 280,
        right: SPACING.paddingX,
        width: 620,
      }}>
        <Tag color="blue">THE ASK</Tag>
        <div style={{
          fontFamily: FONTS.display, fontSize: 140,
          letterSpacing: '-0.03em', lineHeight: 0.9,
          color: COLORS.white, marginTop: 18, marginBottom: 12,
        }}>
          $250K
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: TYPE_SCALE.mono - 2,
          color: COLORS.blueDim, letterSpacing: '0.1em', textTransform: 'uppercase',
          marginBottom: 22,
        }}>
          SEED · 12 MONTHS OF RUNWAY
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            ['40%', 'Mainnet deploy + audits'],
            ['35%', 'First 3 paid pilots'],
            ['25%', 'Team & partner ops'],
          ].map(([pct, use]) => (
            <div key={pct} style={{
              display: 'flex', alignItems: 'center', gap: 16,
              padding: '10px 20px',
              background: 'rgba(30,86,245,0.08)',
              borderLeft: `3px solid ${COLORS.blue}`,
            }}>
              <span style={{
                fontFamily: FONTS.display, fontSize: 28, color: COLORS.blue,
                minWidth: 80,
              }}>{pct}</span>
              <span style={{ fontSize: 20, color: COLORS.white }}>{use}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Closing line bottom */}
      <div style={{
        position: 'absolute', bottom: 110,
        left: SPACING.paddingX, right: 700,
        textAlign: 'left',
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 26,
          color: COLORS.white, letterSpacing: '-0.01em',
          textTransform: 'uppercase', lineHeight: 1.2, marginBottom: 12,
        }}>
          NEXT: THE SETTLEMENT LAYER FOR<br/>
          <span style={{ color: COLORS.blue }}>ANY ONCHAIN AGREEMENT</span> BETWEEN A BRAND AND A PERSON.
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 18,
          color: COLORS.blueDim, letterSpacing: '0.14em', textTransform: 'uppercase',
        }}>
          ERNANI@GECKOVISION.TECH  ·  LETICIA@GECKOVISION.TECH  ·  GECKOVISION.TECH
        </div>
      </div>

      <SlideFooter dark />
    </section>
  );
}

Object.assign(window, {
  Slide05WhySolana, Slide06Market, Slide07Competition, Slide08TeamAsk,
});
