/**
 * Swap sidecar — the durable UNSIGNED-swap-tx builder (e2e Phase 2 §web3 #1).
 *
 * Mirrors the Kamino ts-sidecar (../kamino/ts-sidecar/build_tx.ts): builds an
 * UNSIGNED Solana transaction and emits it as base64 wire bytes on stdout. The
 * difference: this one builds a SWAP via the Jupiter swap API (quote + swap)
 * instead of a klend deposit/withdraw via the SDK.
 *
 * Jupiter's POST /swap returns the FULLY-BUILT base64 transaction directly (the
 * userPublicKey is set as fee-payer/signer but the signature slot is empty — we
 * pass no signing keypair), so this sidecar needs NO npm dependencies: native
 * `fetch` (Node >=22) is the only network primitive. It NEVER signs, NEVER holds
 * a private key, and uses NO secrets — Python signs+submits through the delegated
 * OKX-TEE `wallet contract-call` path (the proven Kamino pattern), or OKX's
 * custodial `swap execute` as the v0 fallback.
 *
 * Input (JSON on stdin, or --json='{...}', or individual --flags):
 *   {
 *     "cluster":         "mainnet" | "devnet",   // informational; Jupiter is mainnet-only
 *     "rpcUrl":          "https://...",            // optional; UNUSED (Jupiter builds the tx)
 *     "inputMint":       "<mint pubkey>",          // token sold (e.g. USDC mint)
 *     "outputMint":      "<mint pubkey>",          // token bought
 *     "amountBaseUnits": "1000000",                // amount of inputMint in base units (string|number)
 *     "slippageBps":     50,                        // 50 = 0.50%
 *     "ownerPubkey":     "<owner/fee-payer pubkey>",
 *     "apiBase":         "https://lite-api.jup.ag", // optional; default lite (no key)
 *     "onlyDirectRoutes": false                     // optional; force single-hop
 *   }
 *
 * Output (one JSON line on stdout):
 *   { "ok": true, "unsignedTxBase64": "...",
 *     "quote": { "inAmount", "outAmount", "otherAmountThreshold",
 *                "priceImpactPct", "slippageBps", "route": [...] },
 *     "inputMint", "outputMint", "amountBaseUnits", "feePayer", "apiBase" }
 *
 * On error: { "ok": false, "error": "<Name>", "message": "<verbatim>" } + exit 1.
 *   The error message includes the verbatim Jupiter API body when the API rejects
 *   (CLAUDE.md: surface failures verbatim, don't rephrase).
 */

type SwapInput = {
  cluster?: string;
  rpcUrl?: string;
  inputMint: string;
  outputMint: string;
  amountBaseUnits: string | number;
  slippageBps: number | string;
  ownerPubkey: string;
  apiBase?: string;
  onlyDirectRoutes?: boolean;
};

// Default Jupiter host. `lite-api.jup.ag` is the keyless free tier; the pro host
// `api.jup.ag` needs an API key (we deliberately do NOT take one — no secrets).
// `quote-api.jup.ag/v6` is the legacy host; lite-api is the current keyless path.
const DEFAULT_API_BASE = "https://lite-api.jup.ag";

function readArg(name: string): string | undefined {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === `--${name}`) return argv[i + 1];
    if (a.startsWith(`--${name}=`)) return a.slice(name.length + 3);
  }
  return undefined;
}

function emit(obj: unknown): void {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function fail(err: unknown): never {
  const message = err instanceof Error ? err.message : String(err);
  const name = err instanceof Error ? err.name : "Error";
  process.stdout.write(JSON.stringify({ ok: false, error: name, message }) + "\n");
  process.exit(1);
}

async function readStdin(): Promise<string> {
  if (process.stdin.isTTY) return "";
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString("utf8").trim();
}

function parseInput(stdinRaw: string): SwapInput {
  const jsonFlag = readArg("json");
  const raw = jsonFlag ?? (stdinRaw || "");
  if (raw) {
    return JSON.parse(raw) as SwapInput;
  }
  return {
    cluster: readArg("cluster") ?? "mainnet",
    rpcUrl: readArg("rpcUrl"),
    inputMint: readArg("inputMint") ?? "",
    outputMint: readArg("outputMint") ?? "",
    amountBaseUnits: readArg("amountBaseUnits") ?? "",
    slippageBps: readArg("slippageBps") ?? "",
    ownerPubkey: readArg("ownerPubkey") ?? "",
    apiBase: readArg("apiBase"),
    onlyDirectRoutes: readArg("onlyDirectRoutes") === "true",
  };
}

function validate(input: SwapInput): void {
  const missing: string[] = [];
  for (const k of ["inputMint", "outputMint", "amountBaseUnits", "slippageBps", "ownerPubkey"] as const) {
    const v = input[k];
    if (v === undefined || v === "" || v === null) missing.push(k);
  }
  if (missing.length) throw new Error(`missing required input field(s): ${missing.join(", ")}`);

  const amt = String(input.amountBaseUnits);
  if (!/^[0-9]+$/.test(amt) || amt === "0") {
    throw new Error(`amountBaseUnits must be a positive integer in base units, got '${amt}'`);
  }
  const slip = Number(input.slippageBps);
  if (!Number.isFinite(slip) || slip < 0 || slip > 10000) {
    throw new Error(`slippageBps must be 0..10000, got ${input.slippageBps}`);
  }
  if (input.inputMint === input.outputMint) {
    throw new Error("inputMint and outputMint are identical — nothing to swap");
  }
}

async function getQuote(base: string, input: SwapInput): Promise<any> {
  const params = new URLSearchParams({
    inputMint: input.inputMint,
    outputMint: input.outputMint,
    amount: String(input.amountBaseUnits),
    slippageBps: String(Number(input.slippageBps)),
  });
  if (input.onlyDirectRoutes) params.set("onlyDirectRoutes", "true");
  const url = `${base}/swap/v1/quote?${params.toString()}`;
  const res = await fetch(url);
  const body = await res.text();
  if (!res.ok) {
    // Surface the Jupiter API's verbatim error body (CLAUDE.md).
    throw new Error(`Jupiter /quote HTTP ${res.status}: ${body}`);
  }
  let quote: any;
  try {
    quote = JSON.parse(body);
  } catch {
    throw new Error(`Jupiter /quote returned non-JSON: ${body.slice(0, 300)}`);
  }
  if (quote?.error) {
    throw new Error(`Jupiter /quote error: ${JSON.stringify(quote.error)}`);
  }
  if (!quote?.outAmount) {
    throw new Error(`Jupiter /quote returned no route/outAmount: ${body.slice(0, 300)}`);
  }
  return quote;
}

async function buildSwapTx(base: string, quote: any, ownerPubkey: string): Promise<string> {
  const url = `${base}/swap/v1/swap`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      quoteResponse: quote,
      userPublicKey: ownerPubkey,
      // We hand the unsigned tx to a delegated signer (OKX TEE); let Jupiter wrap/
      // unwrap SOL for native-SOL legs so the signer needn't manage WSOL ATAs.
      wrapAndUnwrapSol: true,
      // Do NOT auto-create destination ATAs silently with hidden cost; leave Jupiter's
      // default (it adds the ATA ix when needed). No fee account (no secrets/fees here).
    }),
  });
  const body = await res.text();
  if (!res.ok) {
    throw new Error(`Jupiter /swap HTTP ${res.status}: ${body}`);
  }
  let swap: any;
  try {
    swap = JSON.parse(body);
  } catch {
    throw new Error(`Jupiter /swap returned non-JSON: ${body.slice(0, 300)}`);
  }
  if (swap?.error) {
    throw new Error(`Jupiter /swap error: ${JSON.stringify(swap.error)}`);
  }
  if (!swap?.swapTransaction) {
    throw new Error(`Jupiter /swap returned no swapTransaction: ${body.slice(0, 300)}`);
  }
  return swap.swapTransaction as string;
}

async function main(): Promise<void> {
  const stdinRaw = await readStdin();
  const input = parseInput(stdinRaw);
  validate(input);

  const base = (input.apiBase ?? DEFAULT_API_BASE).replace(/\/+$/, "");
  const quote = await getQuote(base, input);
  const unsignedTxBase64 = await buildSwapTx(base, quote, input.ownerPubkey);

  // Flatten the route's AMM labels for an at-a-glance human read (full quote stays
  // server-side; only the shape Python's guard needs is surfaced).
  const route = Array.isArray(quote.routePlan)
    ? quote.routePlan.map((h: any) => h?.swapInfo?.label ?? "unknown")
    : [];

  emit({
    ok: true,
    cluster: input.cluster ?? "mainnet",
    apiBase: base,
    inputMint: input.inputMint,
    outputMint: input.outputMint,
    amountBaseUnits: String(input.amountBaseUnits),
    feePayer: input.ownerPubkey,
    quote: {
      inAmount: String(quote.inAmount ?? input.amountBaseUnits),
      outAmount: String(quote.outAmount),
      // otherAmountThreshold = the min-out the swap enforces given slippageBps.
      otherAmountThreshold: String(quote.otherAmountThreshold ?? ""),
      priceImpactPct: String(quote.priceImpactPct ?? "0"),
      slippageBps: Number(quote.slippageBps ?? input.slippageBps),
      route,
    },
    unsignedTxBase64,
  });
}

main().catch(fail);
