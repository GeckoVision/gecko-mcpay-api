/**
 * STEP 2 — the durable tx-builder.
 *
 * Builds an UNSIGNED Kamino klend deposit/withdraw transaction with
 * @kamino-finance/klend-sdk and emits it as base64 wire bytes on stdout.
 * Cluster-parameterized (devnet | mainnet). NEVER signs, NEVER submits, NEVER
 * touches a private key — Python signs (harness keypair on devnet, delegated
 * OKX-TEE/Privy backend on mainnet later) and submits.
 *
 * Scope (S43 simplest-first): PLAIN klend lend deposit + withdraw. The Multiply
 * flash-loop is a documented follow-on — the action switch leaves an explicit
 * seam for it but does NOT hand-roll the flash sandwich.
 *
 * Input (JSON on stdin, or --json='{...}', or individual --flags):
 *   {
 *     "cluster": "devnet" | "mainnet",
 *     "rpcUrl":  "https://...",            // optional; defaults per cluster
 *     "action":  "deposit" | "withdraw",
 *     "market":  "<lending market pubkey>",
 *     "reserve": "<reserve pubkey>",        // the USDC reserve to deposit into
 *     "amountUsd": 100,                      // human USD (6-dec USDC assumed)
 *     "ownerPubkey": "<owner/fee-payer pubkey>",
 *     "decimals": 6                          // optional, default 6 (USDC)
 *   }
 *
 * Output (one JSON line on stdout):
 *   { "ok": true, "unsignedTxBase64": "...", "numInstructions": N,
 *     "programId": "KLend2g3…", "action": "deposit", "feePayer": "...",
 *     "amountBaseUnits": "100000000", "ixLabels": [...] }
 *
 * On error: { "ok": false, "error": "<Name>", "message": "<verbatim>" } + exit 1.
 */

import { KaminoMarket, KaminoAction, VanillaObligation, noopSigner } from "@kamino-finance/klend-sdk";
import {
  KLEND_PROGRAM_ID,
  RECENT_SLOT_DURATION_MS,
  makeRpc,
  asAddress,
  toBaseUnits,
  buildUnsignedTxBase64,
  readArg,
  emit,
  fail,
} from "./common.ts";
import type { BuildInput, Cluster } from "./common.ts";

async function readStdin(): Promise<string> {
  if (process.stdin.isTTY) return "";
  const chunks: Buffer[] = [];
  for await (const c of process.stdin) chunks.push(c as Buffer);
  return Buffer.concat(chunks).toString("utf8").trim();
}

function parseInput(stdinRaw: string): BuildInput {
  const jsonFlag = readArg("json");
  const raw = jsonFlag ?? (stdinRaw || "");
  if (raw) {
    return JSON.parse(raw) as BuildInput;
  }
  // Fall back to individual flags.
  return {
    cluster: (readArg("cluster") ?? "devnet") as Cluster,
    rpcUrl: readArg("rpcUrl"),
    action: (readArg("action") ?? "deposit") as "deposit" | "withdraw",
    market: readArg("market") ?? "",
    reserve: readArg("reserve") ?? "",
    amountUsd: readArg("amountUsd") ?? "0",
    ownerPubkey: readArg("ownerPubkey") ?? "",
    decimals: readArg("decimals") ? parseInt(readArg("decimals")!, 10) : undefined,
  };
}

function validate(input: BuildInput): void {
  const missing: string[] = [];
  for (const k of ["cluster", "action", "market", "reserve", "amountUsd", "ownerPubkey"] as const) {
    if (input[k] === undefined || input[k] === "" || input[k] === null) missing.push(k);
  }
  if (missing.length) throw new Error(`missing required input field(s): ${missing.join(", ")}`);
  if (input.action !== "deposit" && input.action !== "withdraw") {
    throw new Error(
      `unsupported action ${input.action}: only 'deposit' and 'withdraw' are wired ` +
        "(Multiply flash-loop is a documented follow-on, not hand-rolled here)",
    );
  }
  if (input.cluster !== "devnet" && input.cluster !== "mainnet") {
    throw new Error(`unsupported cluster ${input.cluster}: use 'devnet' or 'mainnet'`);
  }
}

async function main(): Promise<void> {
  const stdinRaw = await readStdin();
  const input = parseInput(stdinRaw);
  validate(input);

  const programId = asAddress(KLEND_PROGRAM_ID[input.cluster]);
  const rpc = makeRpc(input.cluster, input.rpcUrl);
  const owner = noopSigner(asAddress(input.ownerPubkey)); // builds the ix without signing
  const decimals = input.decimals ?? 6;
  const amountBaseUnits = toBaseUnits(input.amountUsd, decimals);

  const market = await KaminoMarket.load(
    rpc as any, // runtime rpc satisfies Rpc<KaminoMarketRpcApi>; widen at boundary
    asAddress(input.market),
    RECENT_SLOT_DURATION_MS,
    programId,
    true, // withReserves — needed so the SDK can resolve reserve oracle/mint accounts
  );
  if (!market) throw new Error(`market ${input.market} not found on ${input.cluster}`);

  const reserve = market.getReserveByAddress(asAddress(input.reserve));
  if (!reserve) {
    throw new Error(`reserve ${input.reserve} not found in market ${input.market}`);
  }

  // A vanilla (plain-lend) obligation, owned by the depositor. The SDK derives
  // the obligation PDA + injects init_user_metadata / init_obligation /
  // refresh_reserve / refresh_obligation setup ixs as needed.
  const obligation = new VanillaObligation(programId);

  // kit's getSlot().send() resolves to a bigint Slot directly (not {value}).
  const currentSlot = await rpc.getSlot().send();

  const common = {
    kaminoMarket: market,
    amount: amountBaseUnits,
    reserveAddress: reserve.address,
    owner,
    obligation,
    useV2Ixs: true,
    scopeRefreshConfig: undefined,
    includeAtaIxs: true,
    requestElevationGroup: false,
    currentSlot,
  };

  const kaminoAction =
    input.action === "deposit"
      ? await KaminoAction.buildDepositTxns(common)
      : await KaminoAction.buildWithdrawTxns(common);

  // Flatten the SDK's labelled ix buckets into a single ordered list. Order
  // matters: compute budget -> setup -> lending -> postLending -> cleanup.
  const ixGroups = [
    [kaminoAction.computeBudgetIxs, kaminoAction.computeBudgetIxsLabels],
    [kaminoAction.setupIxs, kaminoAction.setupIxsLabels],
    [kaminoAction.lendingIxs, kaminoAction.lendingIxsLabels],
    [kaminoAction.postLendingIxs, kaminoAction.postLendingIxsLabels],
    [kaminoAction.cleanupIxs, kaminoAction.cleanupIxsLabels],
  ] as const;

  const instructions: any[] = [];
  const ixLabels: string[] = [];
  for (const [ixs, labels] of ixGroups) {
    ixs.forEach((ix: any, i: number) => {
      instructions.push(ix);
      ixLabels.push(labels?.[i] ?? "unlabeled");
    });
  }

  if (instructions.length === 0) {
    throw new Error("klend-sdk returned 0 instructions — nothing to build");
  }

  const { unsignedTxBase64, numInstructions } = await buildUnsignedTxBase64(
    rpc,
    asAddress(input.ownerPubkey),
    instructions,
  );

  emit({
    ok: true,
    cluster: input.cluster,
    action: input.action,
    programId: KLEND_PROGRAM_ID[input.cluster],
    market: input.market,
    reserve: input.reserve,
    feePayer: input.ownerPubkey,
    amountUsd: String(input.amountUsd),
    amountBaseUnits,
    numInstructions,
    ixLabels,
    luts: kaminoAction.luts.map((l: any) => l.toString()),
    unsignedTxBase64,
  });
}

main().catch(fail);
