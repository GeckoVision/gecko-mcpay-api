/**
 * Shared helpers for the Kamino TS sidecar.
 *
 * The sidecar's ONLY job is to build UNSIGNED transactions with
 * @kamino-finance/klend-sdk and hand them back as base64. It NEVER signs, NEVER
 * holds a private key, NEVER submits — Python (the harness keypair on devnet, a
 * delegated OKX-TEE/Privy backend on mainnet later) does signing + submission.
 *
 * Cluster-parameterized: the same builder works against devnet OR mainnet. Only
 * the {cluster, rpcUrl, market, reserve, programId} inputs change.
 *
 * Node >=22 runs this .ts file directly via native type-stripping (no build
 * step). Keep this file free of TS enums-with-values / namespaces / param
 * properties so type-stripping keeps working without a compiler.
 */

import {
  createSolanaRpc,
  devnet,
  mainnet,
  address,
  pipe,
  createTransactionMessage,
  setTransactionMessageFeePayer,
  setTransactionMessageLifetimeUsingBlockhash,
  appendTransactionMessageInstructions,
  compileTransaction,
  getBase64EncodedWireTransaction,
} from "@solana/kit";
import type { Address, Instruction } from "@solana/kit";

// The full kit RPC type returned by createSolanaRpc. klend-sdk's KaminoMarket.load
// wants a narrower Rpc<KaminoMarketRpcApi>; the runtime object satisfies it, so we
// pass `rpc as any` at the SDK boundary (call sites) rather than fight generics.
export type AnyRpc = ReturnType<typeof createSolanaRpc>;

// Kamino program IDs, cluster-keyed. klend devnet uses the SAME id as mainnet
// (redeployed); only the cluster/RPC + market/reserve accounts differ.
// Verified on-chain 2026-06-04 (S43): KLend2g3… executable on both clusters.
export const KLEND_PROGRAM_ID: Record<string, string> = {
  devnet: "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
  mainnet: "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD",
};

// Default RPCs per cluster (override with rpcUrl on input).
export const DEFAULT_RPC: Record<string, string> = {
  devnet: "https://api.devnet.solana.com",
  mainnet: "https://api.mainnet-beta.solana.com",
};

// Canonical USDC mints per cluster (devnet from the founder's init-devnet.ts).
export const USDC_MINT: Record<string, string> = {
  devnet: "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",
  mainnet: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
};

// recentSlotDurationMs — Solana ~400ms/slot. klend-sdk uses this to age cached
// state; a constant is fine for tx building (not consensus-critical).
export const RECENT_SLOT_DURATION_MS = 450;

export type Cluster = "devnet" | "mainnet";

export type BuildInput = {
  cluster: Cluster;
  rpcUrl?: string;
  action: "deposit" | "withdraw";
  market: string;
  reserve: string;
  amountUsd: number | string;
  ownerPubkey: string;
  // USDC has 6 decimals; overridable for other reserves.
  decimals?: number;
};

export function makeRpc(cluster: Cluster, rpcUrl?: string): AnyRpc {
  const url = rpcUrl ?? DEFAULT_RPC[cluster];
  const wrapped = cluster === "mainnet" ? mainnet(url) : devnet(url);
  // The cluster-tagged ClusterUrl narrows the return type; widen to the plain
  // RPC for our purposes (we use the same method set on both clusters).
  return createSolanaRpc(wrapped) as unknown as AnyRpc;
}

/**
 * Convert a human USD amount to base units (lamports of the token mint).
 * USDC = 6 decimals. Returned as a string so callers can pass it straight to
 * the klend-sdk (which accepts string | BN) without float rounding.
 */
export function toBaseUnits(amountUsd: number | string, decimals: number): string {
  const s = typeof amountUsd === "number" ? amountUsd.toString() : amountUsd;
  const neg = s.startsWith("-");
  const clean = neg ? s.slice(1) : s;
  const [whole, frac = ""] = clean.split(".");
  const fracPadded = (frac + "0".repeat(decimals)).slice(0, decimals);
  const combined = (whole + fracPadded).replace(/^0+/, "") || "0";
  return (neg ? "-" : "") + combined;
}

/**
 * Compile a list of klend-sdk instructions into an UNSIGNED versioned tx and
 * return base64 wire bytes. The fee payer / owner is set but NOT signed — the
 * signature slots are left empty for Python to fill. Uses a real recent
 * blockhash from the cluster (so the tx is submittable for ~60s after build).
 */
export async function buildUnsignedTxBase64(
  rpc: AnyRpc,
  feePayer: Address,
  instructions: Instruction[],
): Promise<{ unsignedTxBase64: string; numInstructions: number }> {
  const { value: latestBlockhash } = await rpc.getLatestBlockhash().send();
  const message = pipe(
    createTransactionMessage({ version: 0 }),
    (m) => setTransactionMessageFeePayer(feePayer, m),
    (m) => setTransactionMessageLifetimeUsingBlockhash(latestBlockhash, m),
    (m) => appendTransactionMessageInstructions(instructions, m),
  );
  const compiled = compileTransaction(message);
  const unsignedTxBase64 = getBase64EncodedWireTransaction(compiled);
  return { unsignedTxBase64, numInstructions: instructions.length };
}

export function asAddress(s: string): Address {
  return address(s);
}

/** Read a single argv flag like --key=value or --key value. */
export function readArg(name: string): string | undefined {
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === `--${name}`) return argv[i + 1];
    if (a.startsWith(`--${name}=`)) return a.slice(name.length + 3);
  }
  return undefined;
}

/** Emit a single JSON line on stdout (the sidecar's only stdout contract). */
export function emit(obj: unknown): void {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

/** Emit an error envelope verbatim (CLAUDE.md: surface failures, don't rephrase) and exit non-zero. */
export function fail(err: unknown): never {
  const message = err instanceof Error ? err.message : String(err);
  const name = err instanceof Error ? err.name : "Error";
  process.stdout.write(JSON.stringify({ ok: false, error: name, message }) + "\n");
  process.exit(1);
}
