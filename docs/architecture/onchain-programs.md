# Gecko On-Chain Programs — Design Blueprint

> **Status:** DESIGN-ONLY (this pass). 0% built. The blueprint **anchor-engineer** and
> **pinocchio-engineer** build against. Companion to [`firewall-e2e.md`](./firewall-e2e.md),
> [`../concepts/solana-101.md`](../concepts/solana-101.md), [`../concepts/jito-101.md`](../concepts/jito-101.md),
> [`../PRD.md`](../PRD.md). Rule sources: [`../../.claude/rules/anchor.md`](../../.claude/rules/anchor.md),
> [`../../.claude/rules/pinocchio.md`](../../.claude/rules/pinocchio.md), [`../../.claude/rules/rust.md`](../../.claude/rules/rust.md).
>
> **Honesty legend:** **DEFENSIBLE** = a clean, shippable-on-devnet v1 with no hand-waving ·
> **ASPIRATIONAL** = real direction, genuinely hard, deferred (size limits, hook registration,
> oracle-key centralization, the NCN).
>
> **The boundary, restated and load-bearing:** Gecko **VERIFIES**. It never executes, custodies,
> reorders, or sits in the Jito auction. Of the two programs below:
> - The **receipt program** is Gecko's own program — Gecko writes verdict hashes it computed.
> - The **firewall/denylist program** is the **issuer/launchpad's** program enforcing **its own**
>   rule. Gecko only *supplies the verdict* that populates the issuer's denylist PDA. Gecko is the
>   oracle that writes a row; the issuer's transfer hook is what reverts a transfer. **Gecko never
>   moves the funds and never blocks the transfer itself.** Do not let any naming or doc imply
>   otherwise.
>
> **Devnet-only** for any future deploy. No mainnet. No real money. No commit/push of keypairs.

---

## 0. TL;DR (the decision)

**Two programs, two frameworks, two engineers, one shared hash contract.**

| Program | Framework | Why | Owner | Status |
|---|---|---|---|---|
| **`gecko-firewall`** — denylist PDA + Token-2022 transfer-hook (`Execute`) | **Pinocchio** | The hook CPI-runs on **every transfer** → CU-critical → the 80-95% CU reduction is the whole point ([`pinocchio.md`](../../.claude/rules/pinocchio.md)). Zero-copy denylist read on the hot path. | **pinocchio-engineer** | DEFENSIBLE core; hook-registration + denylist-size are the hard parts (ASPIRATIONAL beyond v1 bounds) |
| **`gecko-receipt`** — verdict-hash PDA + admin/config | **Anchor** | Cold path (one write per paid verdict, not per transfer). Anchor's account validation + IDL + `declare_program!` buy safety & client-gen with zero CU pressure ([`anchor.md`](../../.claude/rules/anchor.md)). | **anchor-engineer** | DEFENSIBLE v1 |

**The seam between them:** the **canonical hash** already shipped in
`gecko_core/payments/receipt/hash.py` — `receipt_hash(envelope)` = `sha256` of the 4-field
canonical envelope, memo `gecko:v1:{h}`. On-chain `h` **==** off-chain `h`, byte-for-byte. Both
programs store the **same 32-byte `h`**. We do **not** invent a new hash. The Anchor receipt program
is the v1 successor to the shipped v0 devnet SPL-memo anchor (`receipt/anchor.py`) — same `h`, same
`gecko:v1:` schema version, durable PDA instead of an ephemeral memo.

Build order (no collision): **pinocchio-engineer and anchor-engineer can work fully in parallel** —
disjoint crates, disjoint program IDs, the only shared artifact is the **frozen interface contract**
in §7 (PDA seeds + account byte layouts + the `h` contract). Lock §7 first, then both start.

---

## 1. Program decomposition — one program or two?

**Two.** Rejecting a single combined program. The decomposition is forced by three independent axes:

1. **CU profile is opposite.** The hook runs on *every transfer of every Gecko-protected mint* — it
   is the definition of a hot path, and [`pinocchio.md`](../../.claude/rules/pinocchio.md) exists for
   exactly this. The receipt write runs *once per paid verdict* — cold, latency-irrelevant, CU-irrelevant.
   Putting both in one framework means either paying Anchor's ~10-20% overhead on the hot hook (a
   regression on the one thing that must be lean) or hand-rolling the receipt admin surface in
   Pinocchio (throwing away Anchor's validation + IDL on the one thing that benefits from them).
2. **Ownership / trust boundary is opposite.** The receipt program is **Gecko's** (Gecko's oracle
   authority writes Gecko's verdict hashes). The firewall program is **the issuer's** enforcement of
   the issuer's denylist — Gecko is merely an authorized *writer* of one PDA inside it. These are
   different deployers, different upgrade authorities, different audiences. Coupling them in one
   program muddies the verify-not-execute line: a single `gecko-everything` program that both writes
   receipts *and* reverts transfers reads like Gecko enforces. Two programs keep "Gecko writes a row"
   and "the issuer's hook reverts" physically separate.
3. **Upgrade cadence is opposite.** The receipt schema is a **frozen contract** (`gecko:v1:`) — it
   should almost never change. The firewall denylist/hook will iterate (size strategy, eviction,
   multi-mint config) as we learn. Independent programs = independent upgrade authorities and blast
   radius.

**Cross-program calls?** None required between the two. The receipt program never CPIs the firewall
and vice-versa. They share only the off-chain hash contract. (The firewall hook *is* CPI-called by
Token-2022, but that is Token-2022 → firewall, not Gecko-program → Gecko-program.)

```
       OFF-CHAIN (Gecko, Python)                ON-CHAIN (devnet)
  ┌─────────────────────────────┐
  │ verdict envelope (4 fields)  │
  │ → receipt_hash() = h (32B)   │
  └───────────┬─────────────────┘
              │ oracle-signed ix
        ┌─────┴───────────────────────┐
        ▼                             ▼
  gecko-receipt (Anchor)        gecko-firewall (Pinocchio)
  anchor_receipt(h, mint…)      update_denylist(mint, [wallets], h)
  → Receipt PDA = f(h)          → Denylist PDA = f(mint)
  publicly verifiable                    ▲
                                         │ Token-2022 CPI on EVERY transfer
                                  Execute(ctx): read Denylist PDA,
                                  revert if src/dst denied
                                  (issuer's hook, issuer's rule)
```

---

## 2. Account + PDA scheme (the exact byte layout)

Conventions honored: store **canonical bumps** (saves ~1500 CU/access); **one PDA type = one unique
seed prefix** (collision prevention); Anchor space = `T::DISCRIMINATOR.len() + T::INIT_SPACE` (no
magic `8`, Anchor 1.0); Pinocchio uses **single-byte discriminators** + `#[repr(C)]` + byte-array
fields for multi-byte values (alignment-safe, no packed-struct UB).

### 2.1 `gecko-receipt` (Anchor) — accounts

**Program ID:** `GeckoRcpt…` (placeholder; `declare_id!` from the generated keypair at scaffold).

#### `ReceiptConfig` — singleton config + oracle authority

```rust
#[account]
#[derive(InitSpace)]
pub struct ReceiptConfig {
    pub admin: Pubkey,          // 32 — can rotate the oracle; multisig-upgradeable later
    pub oracle: Pubkey,         // 32 — the ONE key allowed to write receipts (Gecko)
    pub bump: u8,               // 1  — canonical bump, STORED
    pub schema_version: u8,     // 1  — 1 == "gecko:v1:" (mirrors RECEIPT_MEMO_PREFIX)
    pub paused: u8,             // 1  — 0/1 kill-switch; admin can halt writes
    pub _reserved: [u8; 27],    // 27 — future use (no realloc churn)
}   // 32+32+1+1+1+27 = 94 data bytes; space = DISCRIMINATOR.len() + INIT_SPACE
```
- **Seeds:** `[b"receipt_config"]` — singleton. One per deployment.
- **Authority model:** `oracle` is a single key **now** (the Gecko devnet oracle keypair already used
  by `receipt/anchor.py`). `admin` can rotate it. Multisig is a later swap of `oracle`/`admin` to a
  Squads PDA — no schema change needed (a `Pubkey` is a `Pubkey`). This is the honest centralization
  point (see §5.4) — the NCN is the real decentralization answer, not v1.

#### `Receipt` — one per anchored verdict

```rust
#[account]
#[derive(InitSpace)]
pub struct Receipt {
    pub h: [u8; 32],            // 32 — THE canonical hash (== off-chain receipt_hash)
    pub oracle: Pubkey,         // 32 — who anchored it (== config.oracle at write time)
    pub slot: u64,              // 8  — Clock::get()?.slot at anchor (the pre-outcome timestamp)
    pub unix_ts: i64,           // 8  — Clock::get()?.unix_timestamp
    pub bump: u8,               // 1  — canonical bump, STORED
    pub schema_version: u8,     // 1  — 1 == gecko:v1
    pub verdict_code: u8,       // 1  — compact gate enum: 0=ok 1=caution 2=block 3=unknown
    pub _reserved: [u8; 21],    // 21 — future use
}   // 32+32+8+8+1+1+1+21 = 104 data bytes
```
- **Seeds:** `[b"receipt", h.as_ref()]` — **one PDA per verdict hash**, content-addressed. Deriving
  the address from `h` is what makes it publicly verifiable: anyone with the off-chain envelope
  recomputes `h`, derives the PDA, fetches it, and checks existence + `h` match. **`h` is exactly 32
  bytes = `MAX_SEED_LEN` → fits one seed slot directly** (verified: Solana `MAX_SEED_LEN = 32`,
  `MAX_SEEDS = 16`; `[b"receipt", h]` is 2 seeds, both ≤ 32 bytes — valid, no hashing-the-hash needed).
- **Why store `h` in the account too** (not just in the seed): a client that *scans* receipts (e.g.
  by oracle) reads `h` without re-deriving; and it lets the on-chain `has_one`-style check assert the
  stored `h` equals the seed-derived one defensively.
- **`verdict_code`** is the only "decision content" on-chain. It is a **bucket**, never a raw score —
  honors the buckets-not-floats rule. The receipt commits to *the hash of the full envelope*; the
  bucket is a convenience index, the hash is the proof.

> **DEFENSIBLE.** `h` is 32 bytes (one seed slot), one account per verdict, ~104 bytes ≈ trivial rent.
> Content-addressing by `h` is the clean idiomatic move.

> **Collision note (honest):** two *different* envelopes producing the same `h` is a sha256 collision —
> not a concern. The real edge case is **anchoring the same `h` twice** (idempotency): the second
> `init` fails because the PDA already exists. That is *correct* (a verdict is anchored once) — handle
> it by treating "PDA exists with matching `h`" as success off-chain, **never** by reaching for
> `init_if_needed` (banned — reinitialization-attack surface, see §5).

### 2.2 `gecko-firewall` (Pinocchio) — accounts

**Program ID:** `GeckoFw…` (placeholder). This program is **deployed by the issuer/launchpad**; Gecko
is an authorized writer. (For the devnet demo, Gecko deploys it to play both roles, but the design
keeps the authority separable.)

#### `FirewallConfig` — per-program config + the Gecko oracle authority

```rust
#[repr(C)]
pub struct FirewallConfig {
    pub admin: [u8; 32],        // 32 — issuer/launchpad admin (deployer)
    pub oracle: [u8; 32],       // 32 — Gecko's key, allowed to write denylists
    pub bump: u8,               // 1  — canonical bump, STORED
    pub paused: u8,             // 1  — issuer kill-switch
    pub _pad: [u8; 6],          // 6  — explicit padding to 8-align (no implicit padding UB)
}   // discriminator(1) + 72 = 73 bytes
```
- **Seeds:** `[b"fw_config"]` — singleton per program deployment.
- **Discriminator:** single byte `0x01` (`DISC_CONFIG`).

#### `Denylist` — per-mint blocked set (the hard one)

The core design question is **how the blocked set is stored**. Three candidates, with the honest
tradeoff, then the recommendation.

| Strategy | Stored form | Pros | Cons |
|---|---|---|---|
| **(a) Explicit pubkey list** | `len: u32` + `[Pubkey; N]` | Simple; exact membership | 32 bytes/entry; 10KB acct cap ≈ ~310 entries; `Execute` does an O(N) scan (CU grows with N) |
| **(b) Bloom/bitmap by hashed wallet** | fixed-size bit array | O(1) `Execute` read; bounded size | false positives (a Bloom blocks an innocent wallet) → **unacceptable** for a near-zero-FP product (PRD NFR) |
| **(c) Per-wallet marker PDAs** | one tiny PDA per `(mint, wallet)` | unbounded set; O(1) `Execute` (derive + check-exists) | one account-creation per blocked wallet (more writes); `Execute` must be handed the marker PDA as an account |

**Recommendation: (c) per-wallet marker PDA, with (a) as a bounded fast-path for small sets.**
Rationale: the FP requirement kills (b). Between (a) and (c), the **block-0 snipe denylist is the
issuer publishing a *small, curated* set before launch** (the snipers Gecko identified), not an
unbounded blocklist — so (a)'s bound (~300) is usually fine and is the **v1 DEFENSIBLE** path. But (a)
makes `Execute` O(N) — every transfer pays for the whole list. **(c) is the scalable answer** and
makes the hot path O(1), at the cost of more setup writes. Ship (a) for v1 (small lists, simplest
hook), design the account layout so (c) is an additive upgrade.

**v1 `Denylist` (strategy a):**
```rust
#[repr(C)]
pub struct DenylistHeader {
    pub mint: [u8; 32],         // 32 — the protected mint
    pub h: [u8; 32],            // 32 — verdict hash that justified this list (provenance → receipt)
    pub count: [u8; 4],         // 4  — u32 LE, # of active entries (byte-array, alignment-safe)
    pub bump: u8,               // 1  — canonical bump, STORED
    pub frozen: u8,             // 1  — 1 = list sealed pre-block-0, no more edits
    pub _pad: [u8; 2],          // 2  — pad to 8-align before the entries
}   // discriminator(1) + 72 header = 73 bytes, then entries follow:
// entries: [[u8; 32]; count]  — packed blocked wallets, appended after header
```
- **Seeds:** `[b"denylist", mint.as_ref()]` — **one denylist PDA per mint**. Deterministic from the
  mint, so the hook can derive it.
- **Discriminator:** single byte `0x02` (`DISC_DENYLIST`).
- **Size:** header (73) + `32 * N`. For N=300 ≈ 9.7KB — under the 10,240-byte `realloc` ceiling, so it
  can be grown via Pinocchio account-realloc as wallets are added (or sized once at create if the set
  is known up-front, which is the launch case). **Bounded at ~300 for v1.** Beyond that → strategy (c).
- **`h` in the header** ties the denylist to the verdict that produced it → the on-chain provenance
  chain: `Denylist.h == Receipt.h == off-chain receipt_hash(envelope)`.
- **`frozen`** lets the issuer seal the list before block-0 (the honest "denylist written *before*
  block 0" posture from `solana-101.md` §8 / `firewall-e2e.md`): once frozen, even the oracle cannot
  edit, so there is no mid-launch tampering surface.

**v2 `DenyMarker` (strategy c, additive):**
```rust
#[repr(C)]
pub struct DenyMarker {            // existence == "this wallet is denied for this mint"
    pub _tag: u8,                  // 1 — DISC_MARKER (0x03); presence is the signal
}
// Seeds: [b"deny", mint.as_ref(), wallet.as_ref()] — O(1) derive in Execute
```
The hook, given the marker PDA for `(mint, src)` / `(mint, dst)`, checks owner + discriminator; exists
⇒ revert. No scan. This is the path past the ~300 bound; ships only if real denylists exceed it.

> **DEFENSIBLE (v1):** strategy (a), bounded ~300, sealed-before-block-0. **ASPIRATIONAL:** strategy
> (c) for unbounded sets — clean upgrade, deferred until the bound bites.

---

## 3. Instruction set (per program, with constraints)

### 3.1 `gecko-receipt` (Anchor)

| Instruction | Signer | Key constraints | Notes |
|---|---|---|---|
| `init_config(oracle: Pubkey)` | `admin` | `init` ReceiptConfig PDA `[b"receipt_config"]`; `payer = admin`; store `bump = ctx.bumps.config`; set `schema_version = 1` | One-time. Not `init_if_needed`. |
| `set_oracle(new_oracle: Pubkey)` | `admin` | `has_one = admin @ Err::Unauthorized`; mutate `config.oracle` | Key rotation → multisig later. |
| `set_paused(paused: bool)` | `admin` | `has_one = admin` | Kill-switch. |
| `anchor_receipt(h: [u8;32], verdict_code: u8)` | `oracle` | `init` Receipt PDA `[b"receipt", h.as_ref()]`, `payer = oracle`; `has_one = oracle` on config (the signer **==** `config.oracle`); `require!(!config.paused)`; `require!(verdict_code <= 3)`; store `slot`/`unix_ts` from `Clock`; store `bump` | The first real caller of the receipt path. Idempotency: re-anchor of same `h` fails on `init` (correct). |
| `close_receipt()` | `admin` | `close = admin`; `has_one`-style admin check via config | Admin-only cleanup (devnet hygiene). Receipts are normally permanent; close is for test teardown. |

**Per-instruction security (applied from [`anchor.md`](../../.claude/rules/anchor.md)):** every account
typed (`Account<'info, T>` / `Signer` / `SystemAccount`); `oracle` must be `Signer`; config is the
authority source (the write key is checked against `config.oracle`, not a passed-in pubkey); no
`init_if_needed`; checked arithmetic only (there is barely any arithmetic here — the slot/ts are reads);
no `unwrap`/`expect`; one `#[error_code]` enum (Anchor 1.0 allows exactly one).

### 3.2 `gecko-firewall` (Pinocchio)

**Two discriminator schemes coexist** — this is a real constraint, not a stylistic choice:
- Gecko's **own** admin instructions use a **single byte on `data[0]`** (the `pinocchio.md` pattern).
- The **`Execute`** instruction is **not ours to name** — Token-2022 CPIs in with the SPL Transfer-Hook
  interface's fixed **8-byte discriminator** = first 8 bytes of `sha256("spl-transfer-hook-interface:execute")`
  = `[105, 37, 101, 197, 75, 251, 102, 26]`. The entrypoint must **first** check whether `data[0..8]`
  matches that 8-byte SPL discriminator (→ hook path) and **otherwise** fall through to the single-byte
  admin match on `data[0]`. (Pick admin disc values that can't collide with `105` as a first byte, or
  branch on length/SPL-disc first — branch on the 8-byte SPL disc first, it's unambiguous.)

`TryFrom` validation pattern per [`pinocchio.md`](../../.claude/rules/pinocchio.md).

| Disc | Instruction | Signer | Key constraints |
|---|---|---|---|
| `0x00` | `InitConfig{oracle}` | `admin` | create FirewallConfig PDA `[b"fw_config"]`; store canonical bump; admin = signer |
| `0x01` | `SetOracle{new_oracle}` | `admin` | validate `signer == config.admin`; write `config.oracle` |
| `0x02` | `UpdateDenylist{mint, wallets[], h, freeze}` | `oracle` | validate `signer == config.oracle`; `require !config.paused`; create-or-extend Denylist PDA `[b"denylist", mint]`; append wallets (dedup); set `count` via **checked** add; write `h`; if `freeze` → set `frozen=1` (and refuse if already frozen) |
| `0x03` | `InitExtraMetas{mint}` | mint authority (issuer) | init the `ExtraAccountMetaList` validation PDA `[b"extra-account-metas", mint]` declaring the Denylist PDA as the one extra account (see §3.4 — the HARD bit) |
| **SPL 8-byte** | `Execute` (Token-2022 transfer hook) | *(none — CPI'd by Token-2022)* | **the hot path** — see §3.3 |
| `0x04` | `CloseDenylist{mint}` | `admin` | mark closed (write `0xff` discriminator), zero, transfer lamports to admin, `close()` — the revival-safe close from `pinocchio.md` |

> **Precedent:** a Pinocchio block-list transfer-hook example already exists in the official
> `solana-developers/program-examples` repo (`tokens/token-2022/transfer-hook/pblock-list/pino`) — the
> exact shape of this program. pinocchio-engineer should start from it, not from scratch.

`UpdateDenylist` is **oracle-signed** (Gecko) but **issuer-gated** (the issuer set `config.oracle =
Gecko` when they deployed; they can revoke). This is the verify-not-execute seam in instruction form:
Gecko *writes the row*; the issuer *chose to honor Gecko's writes* and *owns the program*.

### 3.3 The transfer-hook `Execute` (the CU-critical core)

**The exact account ordering is dictated by the SPL Transfer-Hook interface** (verified against the
`spl-transfer-hook-interface` spec, June 2026) — the hook does **not** get to choose it:

| # | Account | Notes |
|---|---|---|
| 1 | source token account | `[]` |
| 2 | mint | `[]` |
| 3 | destination token account | `[]` |
| 4 | source token account authority | `[]` |
| 5 | **validation account** = `ExtraAccountMetaList` PDA `[b"extra-account-metas", mint]` | the on-chain config that *resolves* the extra accounts |
| 6..n | **extra accounts** resolved from the validation account | **for us: the `Denylist` PDA `[b"denylist", mint]`** (and, strategy (c), the `DenyMarker` PDAs for src/dst owners) |

`amount: u64` is the instruction data. The extra accounts (account #6 = the denylist) are declared once
in the validation account (via `InitExtraMetas`, disc `0x03`) using the `spl-tlv-account-resolution`
`Seed` enum — the seeds for the denylist (`b"denylist"` literal + the mint via `Seed::AccountKey`) are
packed into the 32-byte `address_config`, so **Token-2022's client helper auto-resolves and supplies
the denylist account on every transfer** (the caller doesn't hand-build it). This is why §3.4 is a
mandatory, separate setup step — the hook is inert until the validation account declares the denylist.

```
Execute(accounts, data):
  0. assert data[0..8] == SPL execute discriminator   (it's the hook path, not an admin ix)
  1. parse interface accounts: src_token(1), mint(2), dst_token(3), authority(4),
     validation(5), denylist(6)
  2. ASSERT the transfer is real: read the source token's TransferHookAccount extension
     `transferring` flag — it MUST be true (Token-2022 sets it for the duration of the
     hook CPI). If false → Err(IsNotCurrentlyTransferring). (The canonical whitelist
     example does exactly this — it is the standard hook self-defense.)
  3. re-derive expected Denylist PDA = create_program_address([b"denylist", mint.key, stored_bump])
     → assert denylist(6).key == derived          (never trust the caller-supplied account)
  4. assert denylist(6).owner == THIS program id   (owner check)
  5. assert denylist(6).data[0] == DISC_DENYLIST   (discriminator check)
  6. read src_owner, dst_owner from token accounts (zero-copy)
  7. strategy (a): scan header.count entries; if src_owner OR dst_owner ∈ entries → Err (revert)
     strategy (c): check DenyMarker PDA existence for (mint,src)/(mint,dst) → Err if present
  8. Ok(())  — transfer proceeds
```

> **Note (end-state accounts):** Token-2022 invokes the hook **after** all other transfer logic, so the
> token accounts reflect the *post*-transfer state. We only read *owners* (immutable across the
> transfer), so this doesn't bite us — but a hook that read *balances* would see post-transfer balances.
> Don't design a balance-delta check into this hook.

**Transfer-hook-specific footguns (called out explicitly — these are where hooks bite):**

1. **Assert `transferring == true` — do not merely "be read-only".** Token-2022 sets the
   `TransferHookAccount.transferring` flag on the source/dest accounts **only for the duration of the
   hook CPI**. The standard hook self-defense (the canonical whitelist example) is to **read that flag
   and `Err(IsNotCurrentlyTransferring)` if false** — this is what stops the `Execute` instruction from
   being invoked *standalone* (outside a real transfer) to probe/abuse it. Our hook is additionally
   **read-only** (no state mutation, no CPI, no lamport movement inside `Execute`), which removes any
   re-entrancy surface — but the `transferring` assertion is still **required**, not optional. **Keep
   `Execute` read-only AND assert `transferring`.** (Step 2 above.)
2. **No external calls — by Solana law.** The hook cannot phone Gecko's API ([`solana-101.md`](../concepts/solana-101.md) §1).
   It reads the **pre-published** Denylist PDA only. This is the entire reason the denylist exists.
3. **Caller-supplied PDA must be re-derived, never trusted.** Token-2022 supplies whatever accounts the
   validation account resolved, but a crafted tx could try to pass a *different* (empty) denylist
   account in slot #6. Step 3's re-derivation + owner + discriminator check defeats substitution.
   **This is the #1 hook footgun.**
4. **`ExtraAccountMetaList` registration is itself a setup instruction** (see §3.4 + §5.5 — the
   genuinely hard part). The hook can only *receive* the denylist account if the validation account
   (`[b"extra-account-metas", mint]`, owned by the hook program) was initialized to declare it. Created
   when the mint opts into Gecko's hook.
5. **Fail-direction is ALLOW on ambiguity, REVERT only on a validated hit.** Unlike the off-chain
   signal layer (where `unknown` ≠ pass), the on-chain hook must **not brick a token on its own bug**:
   if the denylist is missing/malformed, **allow** the transfer (the issuer hasn't published a rule).
   A bug that reverts *all* transfers is worse than a missed block. So: **deny only on an explicit,
   validated membership hit; on any ambiguity (no denylist published, parse failure), return Ok** —
   matching the near-zero-FP mandate. (Note this is distinct from footgun #1: a *standalone* call with
   `transferring == false` is always `Err` — that's not "ambiguity", it's an illegitimate invocation.)

### 3.4 `InitExtraMetas` — the validation account (the genuinely hard Token-2022 bit)

Separate setup instruction (`0x03`), run **once per mint** when the mint opts into Gecko's hook
(signed by the **mint authority** — the issuer, not Gecko's oracle). It:
1. Creates the validation PDA `[b"extra-account-metas", mint]` (owned by the firewall program), sized
   for one `ExtraAccountMeta`.
2. Writes, via `spl-tlv-account-resolution`'s `ExtraAccountMetaList::init::<ExecuteInstruction>(...)`,
   a single extra-account config that resolves to the Denylist PDA: seeds =
   `[Seed::Literal(b"denylist"), Seed::AccountKey { index: 1 /* mint */ }]` packed into the 32-byte
   `address_config`, `is_signer=false`, `is_writable=false`.

After this, any `transfer_checked` on the mint (using the standard
`createTransferCheckedWithTransferHookInstruction` client helper) auto-resolves and appends the
denylist account — no caller changes. **This is the fiddly part** (TLV packing, the
`spl-tlv-account-resolution` dependency, the per-mint opt-in flow) and the main integration cost of the
firewall. It is real and works (the SPL example + the Pinocchio `pblock-list` example both do it), but
it is where the engineering time goes.

> **DEFENSIBLE:** read-only `Execute` + `transferring` assert + re-derived PDA + O(N) scan for small
> lists; `InitExtraMetas` via the standard SPL resolution lib. **ASPIRATIONAL / HARD:** the per-mint
> opt-in UX at scale, and the (c) O(1) marker-PDA path.

---

## 4. The off-chain → on-chain seam

The seam reuses the **exact** machinery already shipped. The verdict envelope that Gecko anchors
off-chain today (`receipt/anchor.py`) is the same envelope that drives the on-chain write. Nothing new
is invented in the hash path.

```
 Gecko firewall pipeline (Python, gecko_core/trade_agent/hotpath/)
   LaunchMonitor.recompute → PrecomputedSafety{ gate, snipe, wash, mint, ... }
                                  │
                                  ▼  (verdict envelope: the 4 canonical fields
                                  │   verdict/confidence/citations/dissent — for the
                                  │   PAID oracle path; the firewall gate maps to verdict_code)
                    receipt_hash(envelope) ──► h  (32-byte sha256, gecko:v1)
                                  │
            ┌─────────────────────┴───────────────────────────┐
            ▼                                                   ▼
   gecko-receipt.anchor_receipt(h, verdict_code)      gecko-firewall.update_denylist(
     (oracle-signed Anchor ix; PDA = [b"receipt", h])    mint, denied_wallets, h, freeze)
                                                          (oracle-signed Pinocchio ix;
                                                           PDA = [b"denylist", mint])
            │                                                   │
            ▼                                                   ▼
     Receipt PDA exists @ f(h)                          Denylist PDA @ f(mint), header.h == h
     verifiable: recompute h, derive, fetch             hook reverts denied transfers
```

**Data flow, concretely:**

1. The firewall produces a verdict for a mint (the `PrecomputedSafety` already has `gate` ∈
   {ok,caution,block,unknown}, plus the `snipe` block carrying `fired_signals` and the sniper wallet
   evidence the gate fused).
2. **`gate` → `verdict_code`** (0/1/2/3) — a trivial map, stored on the Receipt for indexing.
3. **`h = receipt_hash(envelope)`** — *the same function the v0 memo anchor calls.* The envelope is
   the 4-field canonical object (`verdict/confidence/citations/dissent`). For the firewall (free)
   surface the envelope is the gate + its evidence projected into that shape; for the paid oracle it's
   the full debate envelope. Either way `h` is computed by the **one** shipped function — on-chain `h`
   == off-chain `h` is guaranteed because *Python computes it and the program only stores the bytes*.
   **The program never recomputes the hash** (it can't — no sha256-of-the-full-envelope on-chain; the
   envelope isn't on-chain). It stores the 32 bytes Gecko hands it. Verifiability comes from the
   *client* recomputing `h` from the envelope it independently holds and checking the PDA.
4. **Receipt write** (always, for every paid/committed verdict): `anchor_receipt(h, verdict_code)` —
   the moat's on-chain anchor, the pre-outcome timestamp (`slot`) baked in.
5. **Denylist write** (only when an issuer has opted in *and* the verdict identifies wallets to block):
   `update_denylist(mint, denied_wallets, h, freeze=true)` — populates the issuer's PDA *before*
   block-0, sealed. The `h` in the denylist header points back at the receipt that justifies it.

**Where this lands in the Python code (for the engineers' awareness, not their build):**
a new `gecko_core/payments/receipt/anchor_pda.py` (Anchor-program client) sits beside the existing
`anchor.py` (memo client), reusing `hash.py` and `config.py` (same oracle keypair, same devnet gate,
same `_assert_devnet`). The denylist client is a new firewall-side module. **web3-engineer owns those
Python clients** — they are out of scope for this on-chain blueprint (the two program engineers build
the *programs*; web3-engineer wires Python → programs later). Flagged here only so the seam is
unambiguous.

> **Honest note on the firewall→denylist arrow:** populating a denylist requires an **issuer who
> deployed the firewall program and set `config.oracle = Gecko`**. There is no such issuer today (the
> commercial seam is unvalidated — `jito-101.md` §8, PRD). For the **devnet demo**, Gecko plays both
> roles on its own mock mint. The arrow is real and DEFENSIBLE *as a mechanism*; the *go-to-market* for
> it is ASPIRATIONAL. Do not let the demo imply a live launchpad integration exists.

---

## 5. Security checklist (applied, per the rules files)

Both programs inherit the full checklists in [`anchor.md`](../../.claude/rules/anchor.md) §"Security
Checklist" and [`pinocchio.md`](../../.claude/rules/pinocchio.md) §"Security Checklist". The
program-specific application:

### 5.1 Account / signer / PDA validation
- **Receipt (Anchor):** `oracle` is `Signer`; the write authority is `config.oracle` (checked, not
  caller-asserted); all accounts typed; Receipt PDA seed = `h` (content-addressed, can't be spoofed to
  a different hash). Config is `has_one = admin`.
- **Firewall (Pinocchio):** every `TryFrom` validates **owner** (`is_owned_by(&crate::ID)`),
  **signer** (`is_signer()` on admin/oracle), **discriminator** (`data[0]`), and **PDA derivation**
  (`create_program_address` with the **stored** bump, never `find_program_address` on the hot path).
  The hook re-derives the denylist PDA and rejects substitution (§3.3 footgun #3).

### 5.2 Stored canonical bumps
Every PDA struct carries `bump: u8`, set once at init from `ctx.bumps.*` (Anchor) /
`find_program_address` (Pinocchio init only), and **reused** everywhere after — the hot `Execute`
path uses `create_program_address(seeds + [stored_bump])`, never a bump search. (~1500 CU/access
saved; on the hook that runs every transfer this is the difference that justifies Pinocchio.)

### 5.3 Banned patterns (hard NOs)
- **NO `init_if_needed`** anywhere — reinitialization-attack surface. Receipt idempotency is handled
  off-chain ("PDA exists with matching `h`" = success), not by re-init.
- **NO `unwrap()` / `expect()`** in program code — `?` + `ok_or(Err)` everywhere. (`unwrap` only in
  tests.)
- **Checked arithmetic only** — `count.checked_add(1).ok_or(Overflow)?` on denylist append;
  `checked_*` for any rent/size math. No `+`/`-`/`*` on the hot path.
- **Duplicate mutable accounts disallowed** (Anchor 1.0 default) — the receipt program does not need
  duplicate-mut; keep the default on. The firewall hook is read-only so the question is moot for
  `Execute`; for `UpdateDenylist`, validate the denylist and config are distinct accounts.
- **Token-2022 via `InterfaceAccount`** (Anchor) / interface-aware mint+token checks (Pinocchio) — the
  hook must work against the **Token Extensions** program (it *is* a Token-2022 hook), so use the
  interface types, not the classic `Token` program types. (The receipt program touches no token
  accounts, so this applies only to the firewall.)

### 5.4 Oracle-key centralization (the honest hard part)
Both programs trust **one Gecko `oracle` key** to write truth. That key, compromised, can write a
false denylist (brick wallets on an opted-in mint) or false receipts (anchor a hash for an envelope
that doesn't exist — though a verifier recomputing `h` catches a *mismatched* envelope; it can't catch
a *fabricated* one if the attacker also fabricates the envelope). Mitigations, in order of when:
- **v1 (now):** single key, `admin`-rotatable, `paused` kill-switch, devnet-only. Honest and bounded.
- **v1.5:** `oracle` / `admin` → a **Squads multisig PDA** (no schema change — it's still a `Pubkey`).
- **v3 (ASPIRATIONAL, ~2027):** the **Verification NCN** (`jito-101.md` §8 / PRD roadmap) — operators
  run the panel, stakers back honesty, slashing if a verdict contradicts its evidence. *That* is the
  real decentralization of the oracle authority, not a multisig. Do not claim v1 is decentralized.

### 5.5 Transfer-hook-specific (the footguns, from §3.3, consolidated)
- **Assert `TransferHookAccount.transferring == true`** at the top of `Execute` (`Err` otherwise) —
  the standard hook self-defense against standalone invocation. Read-only `Execute` *additionally*
  removes any re-entrancy/mutation surface — but the `transferring` assert is **required, not replaced
  by** being read-only. **Keep `Execute` read-only AND assert `transferring`.**
- Re-derive the denylist PDA in the hook (`create_program_address` + stored bump); never trust the
  caller-passed account in slot #6 (substitution attack — the #1 footgun).
- Owner + discriminator check on the denylist account before reading it.
- **Allow-on-ambiguity, revert-only-on-hit:** deny only on a *validated membership hit*; on
  missing/malformed denylist, **allow** — never brick a token via a hook bug. (§3.3 #5. Distinct from
  the `transferring` assert, which always rejects an illegitimate standalone call.)
- The validation account (`[b"extra-account-metas", mint]`) is set up by a **separate** `InitExtraMetas`
  ix (§3.4); the hook is inert until it declares the denylist. **HARD** — TLV packing via
  `spl-tlv-account-resolution` is the genuinely fiddly Token-2022 part.

### 5.6 Surfpool / autofixer gate
Per the rules: any program Rust the engineers write **must** be run through the `program_autofixer`
MCP tool (loop until `require_another_tool_call_after_fixing` is false) before it's considered done.
This blueprint pre-empts the common findings (checked math, stored bumps, no `init_if_needed`, owner
checks) so the autofixer should be clean on those axes.

---

## 6. Workspace layout + test/deploy stack

### 6.1 Where the programs live

The Python uv workspace is untouched. A new **`programs/`** tree at repo root holds the on-chain code,
isolated from Python (different toolchain, different CI lane):

```
programs/
├── Anchor.toml                      # Anchor 1.0 workspace manifest (targets Agave 3.x)
├── Cargo.toml                       # Rust workspace: members = receipt + firewall
├── README.md                        # "these are devnet-only; see docs/architecture/onchain-programs.md"
├── gecko-receipt/                   # ANCHOR program  (anchor-engineer)
│   ├── Cargo.toml
│   ├── Xargo.toml
│   └── src/
│       ├── lib.rs                   # declare_id!, #[program], one #[error_code]
│       ├── state.rs                 # ReceiptConfig, Receipt
│       ├── instructions/
│       │   ├── mod.rs
│       │   ├── init_config.rs
│       │   ├── set_oracle.rs
│       │   ├── anchor_receipt.rs
│       │   └── close_receipt.rs
│       └── errors.rs
├── gecko-firewall/                  # PINOCCHIO crate (pinocchio-engineer)
│   ├── Cargo.toml                   # pinocchio + pinocchio-token (interface) only; no_std-friendly
│   └── src/
│       ├── lib.rs                   # entrypoint! / lazy_program_entrypoint!, disc match
│       ├── state.rs                 # FirewallConfig, DenylistHeader, (DenyMarker v2)
│       ├── instructions/
│       │   ├── mod.rs
│       │   ├── init_config.rs
│       │   ├── update_denylist.rs
│       │   ├── execute.rs           # the transfer hook — the hot path
│       │   └── close_denylist.rs
│       ├── extra_metas.rs           # ExtraAccountMetaList init (the hard Token-2022 bit)
│       └── errors.rs
└── tests/
    ├── litesvm/                     # Rust LiteSVM unit tests (Anchor 1.0 default template)
    │   ├── receipt_tests.rs
    │   └── firewall_tests.rs
    ├── mollusk/                     # Mollusk CU benches for the Pinocchio hook (CU is the point)
    │   └── execute_cu_bench.rs
    └── surfpool/                    # integration vs forked mainnet (we already run surfpool)
        └── hook_against_fork.rs
```

**Why a sibling `programs/` and not under `packages/`:** `packages/` is the Python uv workspace; mixing
a Cargo/Anchor workspace inside it confuses both toolchains and the existing CI. `programs/` is the
conventional Anchor location and keeps the Rust lane clean. The Pinocchio crate lives *inside* the
Anchor workspace tree for one `cargo`/test surface, but is a **plain Pinocchio crate** (not an Anchor
program) — `Anchor.toml` lists it under `[programs.devnet]` for deploy convenience only.

### 6.2 `Anchor.toml` (the shape — empty-stub recommendation only)

```toml
[toolchain]
anchor_version = "1.0.0"            # Anchor 1.0 (Solana 3.x / Agave; bundles its own toolchain)

[features]
resolution = true
skip-lint = false

[programs.devnet]
gecko_receipt  = "GeckoRcpt1111111111111111111111111111111111"   # placeholder; real key at scaffold
gecko_firewall = "GeckoFw111111111111111111111111111111111111"   # placeholder

[registry]
url = "https://api.apr.dev"

[provider]
cluster = "devnet"                  # DEVNET ONLY — never set mainnet here
wallet = "~/.config/solana/gecko-oracle-devnet.json"   # gitignored; the same oracle keypair family

[scripts]
test = "cargo test"                 # Anchor 1.0 default test template is LiteSVM (Rust)
```

### 6.3 Test / deploy stack (per the rules)

| Layer | Tool | What it proves | Rule source |
|---|---|---|---|
| **Unit** | **LiteSVM** (Rust, Anchor 1.0 default) | Receipt init/anchor/close logic; denylist write/append/freeze; `Execute` allow/deny branches | `anchor.md` (LiteSVM default), `rust.md` (no solana-test-validator for unit) |
| **CU bench** | **Mollusk** | The `Execute` hook's CU on allow vs deny, vs the ~300-entry scan ceiling — **the number that justifies Pinocchio** | `pinocchio.md` §"Testing with Mollusk" |
| **Integration** | **Surfpool** (forked mainnet) | A real Token-2022 mint with the hook registered, a real transfer reverting against a sealed denylist — **reuse the firewall fork we already run** | `anchor.md` (`anchor test`/`localnet` use Surfpool), `firewall-e2e.md` (surfpool fork demo) |
| **Deploy** | `anchor deploy --provider.cluster devnet` | Devnet program deploy; the demo's anchor | DEVNET ONLY |

**Anchor-1.0 / Agave-3.x specifics the engineers must honor:** TS client (if any) is
`@anchor-lang/core` (not `@coral-xyz/anchor`); SPL token CPIs use `transfer_checked` (the firewall
hook doesn't transfer, but any test harness that mints/transfers does); space = `DISCRIMINATOR.len() +
INIT_SPACE`; one `#[error_code]` enum; `CpiContext::new` takes a `Pubkey`. The default integration
runner is **Surfpool**, not `solana-test-validator`.

The CU-regression guard: wire the Mollusk `Execute` bench into the `/benchmark` skill pattern so the
hook's CU is tracked against a baseline (a hook that regresses to Anchor-like CU defeats its reason to
exist).

---

## 7. Build order for the two engineers (the frozen interface)

**Both engineers start in parallel.** Disjoint crates, disjoint program IDs, no CPI between them. The
**only** shared artifact is this frozen interface contract — lock it before either writes code, and
neither can break the other.

### 7.1 THE SHARED CONTRACT (freeze this first — the one-way door)

Per `firewall-e2e.md` §8, the receipt hash spec and the row schema are the one-way-door decisions.
Frozen values both engineers (and web3-engineer's Python clients) must honor verbatim:

| Contract item | Frozen value | Source of truth |
|---|---|---|
| **Hash `h`** | `sha256(canonical_json(envelope))`, 32 bytes, lowercase hex off-chain | `gecko_core/payments/receipt/hash.py::receipt_hash` — **DO NOT reimplement on-chain** |
| **Schema version** | `gecko:v1:` → `schema_version = 1` (u8) on both `Receipt` and `Denylist` | `RECEIPT_MEMO_PREFIX` |
| **`verdict_code`** | `0=ok 1=caution 2=block 3=unknown` | this doc (mirrors `precomputed.safety_gate` outputs) |
| **Receipt PDA seeds** | `[b"receipt", h]` (h = 32 raw bytes) | this doc |
| **ReceiptConfig seeds** | `[b"receipt_config"]` | this doc |
| **Denylist PDA seeds** | `[b"denylist", mint]` | this doc |
| **FirewallConfig seeds** | `[b"fw_config"]` | this doc |
| **Validation (ExtraAccountMetaList) seeds** | `[b"extra-account-metas", mint]` | SPL transfer-hook convention (fixed — Token-2022's client helper derives it) |
| **`Execute` discriminator** | SPL 8-byte = `sha256("spl-transfer-hook-interface:execute")[0..8]` = `[105,37,101,197,75,251,102,26]` | SPL transfer-hook interface (NOT ours to choose) |
| **DenyMarker seeds (v2)** | `[b"deny", mint, wallet]` | this doc |
| **Account byte layouts** | exactly §2.1 / §2.2 (field order, sizes, reserved tails) | this doc |
| **Provenance link** | `Denylist.header.h == Receipt.h == off-chain h` | this doc |

If any of these must change, it's a coordinated change to **both** programs + the Python clients + a
new test vector — treat like a `gecko:v1:`→`v2:` bump.

### 7.2 pinocchio-engineer builds (`gecko-firewall`)

Sequence (each step independently testable):
1. **`FirewallConfig` + `InitConfig`/`SetOracle`** — config PDA, stored bump, admin/oracle, `TryFrom`
   validation (owner/signer/disc). LiteSVM unit test.
2. **`DenylistHeader` + `UpdateDenylist`** — create/extend the per-mint PDA, append+dedup wallets,
   checked `count`, `h` provenance, `freeze`. Bounded ~300 (strategy a). LiteSVM unit test for
   append/freeze/refuse-edit-when-frozen.
3. **`extra_metas.rs` — `InitExtraMetas` (disc `0x03`)** — the HARD part; do it **before** the e2e hook
   test (the hook is inert without it). Creates the validation PDA `[b"extra-account-metas", mint]` and
   writes one `ExtraAccountMeta` resolving to the denylist (seeds `Literal(b"denylist")` +
   `AccountKey{index:1}`) via `spl-tlv-account-resolution`. LiteSVM test: validation account decodes.
4. **`Execute` (the hook)** — the 8-byte SPL-disc entrypoint branch; assert `transferring==true`;
   re-derive denylist PDA (stored bump); owner+disc check; scan; revert on hit; **allow on
   ambiguity**. The §3.3 footgun matrix is the test set (standalone call `transferring=false` → Err;
   substituted denylist account → reject; missing denylist → allow; denied src → revert; denied dst →
   revert; clean → allow). **Surfpool integration:** a real Token-2022 mint (hook-configured) + a real
   `transfer_checked` reverting against a sealed denylist — reuses the firewall fork we already run.
5. **`CloseDenylist`** — the revival-safe close (`0xff` disc, zero, close).
6. **Mollusk CU bench** on `Execute` — the deliverable number (allow vs deny, vs the N≤300 scan ceiling).

**Owns:** the whole `gecko-firewall/` crate + the Mollusk bench + the surfpool hook test.

### 7.3 anchor-engineer builds (`gecko-receipt`)

Sequence:
1. **`ReceiptConfig` + `init_config`/`set_oracle`/`set_paused`** — singleton config, stored bump,
   `has_one = admin`, one `#[error_code]` enum. LiteSVM unit test.
2. **`Receipt` + `anchor_receipt`** — content-addressed PDA `[b"receipt", h]`, `init` (NOT
   `init_if_needed`), `oracle` signer == `config.oracle`, `verdict_code <= 3`, `Clock` slot/ts. The
   first real caller of the receipt path. LiteSVM test for: write, idempotent re-write fails, wrong
   signer rejected, paused rejects.
3. **`close_receipt`** — admin-only `close` for test teardown.
4. **IDL** — Anchor generates it; confirm `declare_program!`-consumable (the receipt program's IDL is
   what a TS/Python client uses to derive the PDA + build the ix). This is Anchor's reason-to-exist
   here — the firewall (Pinocchio) has no auto-IDL, so the receipt program carries the client-gen
   weight.

**Owns:** the whole `gecko-receipt/` Anchor program + its LiteSVM tests + the generated IDL.

### 7.4 Collision avoidance (explicit)
- **Disjoint files** — different crates under `programs/`. No shared Rust module.
- **Disjoint program IDs** — two `declare_id!` (Anchor) / `crate::ID` (Pinocchio).
- **No CPI between them** — the only coupling is the §7.1 contract (off-chain hash + seed strings +
  byte layouts), which is data, not code. Neither imports the other.
- **Shared test mint helper** (optional) — if both want a Token-2022 mint fixture for surfpool, put it
  in `programs/tests/common/` and treat it as read-only shared test scaffolding (per the parallel-code
  rule: read-only shared, writes isolated).
- **web3-engineer is downstream** — the Python clients (`anchor_pda.py`, denylist client) come *after*
  both programs have stable IDLs/layouts. Not part of this parallel pass.

---

## 8. What's DEFENSIBLE vs ASPIRATIONAL (the honest ledger)

| Item | Verdict | Why |
|---|---|---|
| Receipt PDA content-addressed by `h`, reusing the shipped hash | **DEFENSIBLE** | `h` is 32B = one seed; the hash function already exists + is a frozen contract; pure storage on-chain |
| Single oracle key, admin-rotatable, paused kill-switch, devnet | **DEFENSIBLE (bounded)** | Honest v1; the centralization is named, not hidden |
| Read-only transfer hook, re-derived PDA, fail-open on ambiguity | **DEFENSIBLE** | Sidesteps re-entrancy by construction; matches near-zero-FP mandate |
| Denylist strategy (a): bounded ~300, sealed-before-block-0 | **DEFENSIBLE (v1)** | The launch denylist is small + curated; fits one account; O(N) scan acceptable at N≤300 |
| Two-program split, two frameworks | **DEFENSIBLE** | CU/ownership/upgrade axes all point the same way |
| `ExtraAccountMetaList` registration UX | **HARD / partly ASPIRATIONAL** | The fiddly Token-2022 reality; works, but the per-mint opt-in flow is real engineering |
| Denylist strategy (c): unbounded via marker PDAs, O(1) hook | **ASPIRATIONAL** | Clean upgrade; deferred until the ~300 bound bites |
| A live launchpad/issuer actually deploying the hook + setting `oracle=Gecko` | **ASPIRATIONAL (commercial)** | No design partner today (PRD/`jito-101.md` §8); the *mechanism* is real, the *adoption* is unvalidated |
| Multisig oracle (v1.5) | **DEFENSIBLE when needed** | No schema change; a `Pubkey` swap to a Squads PDA |
| Verification NCN as the real oracle decentralization | **ASPIRATIONAL (~2027)** | The rail, not v1; restaking arm, JIP-fundable, no partner yet |
| Denylist as the *primary* product | **NOT THE PRODUCT** | Gecko verifies; the hook is the issuer's enforcement of its own rule — a switching-cost feature, not the moat (the moat is the graded verdict ledger, PRD) |

**The one-way doors (spend rigor here before any code):** the §7.1 frozen contract — specifically the
**hash reuse** (`h` from `hash.py`, never reimplemented on-chain) and the **PDA seed strings + byte
layouts**. Everything else (instruction internals, file split, the (a)→(c) denylist upgrade) is
two-way and can iterate.

---

## 9. Sources (the Solana-mechanics facts verified for this blueprint, June 2026)

The hard Token-2022 / PDA facts above were checked against current docs (not memory):
- **Transfer-Hook interface `Execute` account ordering + 8-byte discriminator** — `spl-transfer-hook-interface`
  specification (source/mint/dest/authority/validation + n extra; disc =
  `sha256("spl-transfer-hook-interface:execute")[0..8]`).
- **`ExtraAccountMetaList` validation account + `spl-tlv-account-resolution`** — solana-program.com
  Transfer-Hook docs + `solana-developers/program-examples` (`transfer-hook/whitelist` Anchor,
  `transfer-hook/pblock-list/pino` Pinocchio — the block-list precedent).
- **`TransferHookAccount.transferring` flag + `IsNotCurrentlyTransferring`** — the canonical whitelist
  example's hook self-defense; the flag is set by Token-2022 for the hook CPI duration.
- **Hook runs after transfer logic (end-state accounts)** — solana-program.com extensions guide.
- **PDA limits `MAX_SEED_LEN = 32`, `MAX_SEEDS = 16`, `create_program_address` ≈ 1500 CU** — Solana
  PDA core docs (so `[b"receipt", h(32B)]` is valid, and the stored-bump hot-path matters).
- **Anchor 1.0 / Pinocchio conventions** — repo rules files (`.claude/rules/{anchor,pinocchio,rust}.md`).

Anything DAO-governed or fast-moving (BAM/NCN specifics) is deferred to `jito-101.md`'s dated sources;
this doc only depends on the stable Token-2022 / PDA mechanics above.

---

*Gecko — On-Chain Programs Design Blueprint · design-only · devnet-only · June 2026. Implementation
handoff: `gecko-firewall` → pinocchio-engineer, `gecko-receipt` → anchor-engineer. Companion to
`firewall-e2e.md` (the e2e map this slots into at the ENFORCEMENT + LEDGER edges).*
