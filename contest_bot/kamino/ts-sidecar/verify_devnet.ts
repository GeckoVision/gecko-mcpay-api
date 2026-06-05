/**
 * STEP 1 (S43 known-risk): does klend list a USABLE devnet USDC reserve with a
 * working oracle (price)? This decides whether the on-chain proof runs on devnet
 * or must wait for the (founder-gated) mainnet step.
 *
 * Approach (chain is ground truth, docs lie):
 *   1. getProgramAccounts for klend `LendingMarket` on the target cluster.
 *   2. KaminoMarket.load(...) each (bounded) with reserves.
 *   3. For each market, scan reserves for the cluster USDC mint; report whether
 *      it has an oracle price (getOracleMarketPrice > 0) and available liquidity.
 *
 * Output: a JSON summary on stdout. No tx is built, nothing is signed.
 *
 * Usage:
 *   node verify_devnet.ts                 # devnet, default RPC
 *   node verify_devnet.ts --cluster=devnet --rpcUrl=https://... --maxMarkets=40
 *   node verify_devnet.ts --cluster=mainnet --maxMarkets=3   # sanity-check the path on mainnet
 */

import { KaminoMarket } from "@kamino-finance/klend-sdk";
import { getBase58Decoder } from "@solana/kit";
import {
  KLEND_PROGRAM_ID,
  USDC_MINT,
  RECENT_SLOT_DURATION_MS,
  makeRpc,
  asAddress,
  readArg,
  emit,
  fail,
} from "./common.ts";
import type { Cluster } from "./common.ts";

// LendingMarket Anchor discriminator (first 8 bytes). Pulled from the codegen
// account class at runtime so it stays correct across SDK versions.
async function lendingMarketDiscriminatorBase58(): Promise<string> {
  const mod: any = await import("@kamino-finance/klend-sdk");
  const disc: Uint8Array = mod.LendingMarket.discriminator;
  return getBase58Decoder().decode(disc);
}

async function main(): Promise<void> {
  const cluster = (readArg("cluster") ?? "devnet") as Cluster;
  const rpcUrl = readArg("rpcUrl");
  const maxMarkets = parseInt(readArg("maxMarkets") ?? "30", 10);

  const rpc = makeRpc(cluster, rpcUrl);
  const programId = asAddress(KLEND_PROGRAM_ID[cluster]);
  const usdcMint = USDC_MINT[cluster];

  const discriminator = await lendingMarketDiscriminatorBase58();

  // Enumerate LendingMarket accounts via memcmp on the discriminator at offset 0.
  const gpa = await (rpc as any)
    .getProgramAccounts(programId, {
      encoding: "base64",
      dataSlice: { offset: 0, length: 0 },
      filters: [{ memcmp: { offset: 0n, bytes: discriminator, encoding: "base58" } }],
    })
    .send();

  const marketAddrs = gpa.map((a: any) => a.pubkey).slice(0, maxMarkets);

  const throttleMs = parseInt(readArg("throttleMs") ?? "1500", 10);
  const findings: any[] = [];
  let usableMarket: string | null = null;
  let usableReserve: string | null = null;
  let rateLimited = false;

  for (const marketAddr of marketAddrs) {
    if (throttleMs > 0) await new Promise((r) => setTimeout(r, throttleMs));
    let market: KaminoMarket | null = null;
    try {
      market = await KaminoMarket.load(
        rpc as any, // runtime rpc satisfies Rpc<KaminoMarketRpcApi>
        asAddress(marketAddr),
        RECENT_SLOT_DURATION_MS,
        programId,
        true, // withReserves
      );
    } catch (e) {
      const msg = (e as Error).message;
      // The SDK throws "Could not find oracle for <SYMBOL>" when a reserve has
      // no working oracle — that IS the devnet USDC-no-oracle signal. Record it.
      const noOracleUsdc = /Could not find oracle for USDC/i.test(msg);
      if (/429|Too Many Requests/i.test(msg)) rateLimited = true;
      findings.push({ market: marketAddr, error: msg, usdcNoOracle: noOracleUsdc });
      continue;
    }
    if (!market) continue;

    let usdcReserve: any = null;
    for (const r of market.getReserves()) {
      let mint: string;
      try {
        mint = r.getLiquidityMint().toString();
      } catch {
        continue;
      }
      if (mint === usdcMint) {
        usdcReserve = r;
        break;
      }
    }
    if (!usdcReserve) continue;

    let price = "n/a";
    let hasOracle = false;
    let liquidity = "n/a";
    try {
      const p = usdcReserve.getOracleMarketPrice();
      price = p.toString();
      hasOracle = Number(price) > 0;
    } catch (e) {
      price = `oracle-error: ${(e as Error).message}`;
    }
    try {
      liquidity = usdcReserve.getLiquidityAvailableAmount().toString();
    } catch {
      /* ignore */
    }

    const symbol = (() => {
      try {
        return usdcReserve.getTokenSymbol();
      } catch {
        return "?";
      }
    })();

    const entry = {
      market: marketAddr,
      reserve: usdcReserve.address.toString(),
      symbol,
      mint: usdcMint,
      hasOracle,
      price,
      liquidityAvailable: liquidity,
    };
    findings.push(entry);
    if (hasOracle && usableMarket === null) {
      usableMarket = marketAddr;
      usableReserve = usdcReserve.address.toString();
    }
  }

  emit({
    ok: true,
    cluster,
    programId: KLEND_PROGRAM_ID[cluster],
    usdcMint,
    marketsScanned: marketAddrs.length,
    marketsTotalFound: gpa.length,
    usdcReservesFound: findings.filter((f) => f.reserve).length,
    usdcReservesWithoutOracle: findings.filter((f) => f.usdcNoOracle).length,
    rateLimited,
    usableForOnChainProof: usableMarket !== null,
    usableMarket,
    usableReserve,
    findings,
  });
}

main().catch(fail);
