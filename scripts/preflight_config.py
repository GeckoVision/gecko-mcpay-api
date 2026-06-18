"""LOCAL preflight config-parity check — run BEFORE every deploy.

WHY THIS EXISTS (the bug it catches): OKX news went DARK in prod because
``infra/push-ssm-params.sh`` errored mid-run and never pushed
``OKX_TRADING_SECRET_KEY`` + ``OKX_TRADING_PASSPHRASE`` to SSM. Locally
everything worked (the creds were in ``.env``); prod got a partial credential
set → OKX returned HTTP 401 → the adapter fail-OPENed to ``[]`` → silent dark
wedge. The class of bug is "works locally but missing/wrong in PRD" — a
local≠SSM config drift. This script catches it before the deploy, not after.

WHAT IT DOES, per ENABLED provider (a provider is "enabled" when its flag/usage
env says so, e.g. ``GECKO_NEWS_PROVIDER=okx``):
  1. LOCAL check — assert every required cred is present + non-sentinel in the
     loaded environment (``.env`` via ``set -a; source .env``).
  2. SSM check (``--check-ssm``) — read back each cred's SSM param via the
     ``aws`` CLI (presence + is-sentinel ONLY, value never fetched-then-printed)
     and DIFF local-has vs SSM-has. Any provider configured locally but
     sentinel/absent in SSM is flagged RED — that is the drift that bit us.
  3. Optional live auth ping (``--ping``) for OKX news — reuses the secret-safe
     HMAC probe pattern: prints only HTTP status + OKX code, never creds.

SECRET-SAFETY: this script NEVER prints a secret value. It prints only env-var
NAMES, presence booleans, the literal ``__unset__`` sentinel marker, HTTP
status codes, and OKX error codes. ``aws ssm get-parameter`` is invoked with a
``--query`` that yields the value, but the value is only compared to the
sentinel string in-process and then dropped — it is never echoed.

USAGE:
    set -a; source .env; set +a
    uv run python scripts/preflight_config.py                 # local-only
    uv run python scripts/preflight_config.py --check-ssm     # local vs SSM diff
    uv run python scripts/preflight_config.py --check-ssm --ping
    uv run python scripts/preflight_config.py --region us-east-2

EXIT CODE: non-zero if any enabled provider is mis-provisioned locally or (with
--check-ssm) drifts between local and SSM. Wire it into a pre-deploy gate.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field

SSM_PREFIX = "/gecko-api"
SENTINEL = "__unset__"


def _clean(name: str) -> str:
    """Env value, stripped, with the SSM sentinel treated as unset.

    Mirrors ``news_factory._env_clean`` / ``safety_check._env_clean`` — the
    single house convention for "is this cred really set".
    """
    value = os.environ.get(name, "").strip()
    return "" if value == SENTINEL else value


def _is_enabled_okx_news() -> bool:
    return _clean("GECKO_NEWS_PROVIDER").lower() == "okx"


def _is_enabled_simple(flag: str, *enabled_values: str) -> bool:
    return _clean(flag).lower() in enabled_values


@dataclass
class Provider:
    """One configurable provider and the creds it needs when enabled."""

    name: str
    enabled: bool
    # SSM-param names (== env var names here) that MUST be real when enabled.
    required: list[str] = field(default_factory=list)
    # Optional creds — checked/reported but not required for "configured".
    optional: list[str] = field(default_factory=list)
    note: str = ""


def _discover_providers() -> list[Provider]:
    """Build the provider list from the current environment.

    A provider only gates the run when it is ENABLED — a disabled provider with
    sentinel creds is the intended default and never fails preflight.
    """
    return [
        Provider(
            name="okx-news",
            enabled=_is_enabled_okx_news(),
            required=["OKX_TRADING_API_KEY", "OKX_TRADING_SECRET_KEY"],
            optional=["OKX_TRADING_PASSPHRASE"],
            note="GECKO_NEWS_PROVIDER=okx ⇒ OKX V5 HMAC news. Passphrase optional "
            "but if the key was issued with one it is REQUIRED for auth (401 otherwise).",
        ),
        Provider(
            name="okx-onchainos",
            # Enabled when a real OnchainOS key is present (no separate flag).
            enabled=bool(_clean("OKX_ONCHAINOS_API_KEY")),
            required=["OKX_ONCHAINOS_API_KEY"],
            note="OnchainOS market client (token metrics / holders). Disabled = sentinel.",
        ),
        Provider(
            name="solana-rpc",
            # Either Helius OR a full QuickNode RPC URL enables the safety read.
            enabled=bool(_clean("HELIUS_API_KEY")) or bool(_clean("QUICKNODE_RPC_URL")),
            required=[],  # at-least-one — validated specially below
            optional=["HELIUS_API_KEY", "QUICKNODE_RPC_URL"],
            note="Safety/Information-MEV read. Needs Helius key OR QuickNode RPC URL.",
        ),
        Provider(
            name="dune",
            enabled=bool(_clean("DUNE_API_KEY")),
            required=["DUNE_API_KEY"],
            note="Dune aggregate queries. Disabled = sentinel (fail-OPEN).",
        ),
        Provider(
            name="voyage-embed",
            enabled=_is_enabled_simple("EMBED_PROVIDER", "voyage"),
            required=["VOYAGE_API_KEY"],
            note="EMBED_PROVIDER=voyage ⇒ Voyage embeddings need VOYAGE_API_KEY.",
        ),
        Provider(
            name="voyage-rerank",
            enabled=_is_enabled_simple("GECKO_RERANKER", "voyage"),
            required=["VOYAGE_API_KEY"],
            note="GECKO_RERANKER=voyage ⇒ reranker needs VOYAGE_API_KEY.",
        ),
        Provider(
            name="mongo",
            enabled=_is_enabled_simple("GECKO_CHUNK_STORE", "mongo")
            or _is_enabled_simple("GECKO_TRANSCRIPT_STORE", "mongo"),
            required=["MONGODB_URI"],
            note="GECKO_CHUNK_STORE/TRANSCRIPT_STORE=mongo ⇒ needs MONGODB_URI.",
        ),
    ]


# --- Local check -------------------------------------------------------------


def _local_status(p: Provider) -> tuple[bool, list[str]]:
    """Return (ok, problems) for a provider's LOCAL env state."""
    problems: list[str] = []
    if p.name == "solana-rpc":
        if not (_clean("HELIUS_API_KEY") or _clean("QUICKNODE_RPC_URL")):
            problems.append(
                "neither HELIUS_API_KEY nor QUICKNODE_RPC_URL is set (both sentinel/absent)"
            )
        return (not problems, problems)
    for var in p.required:
        if not _clean(var):
            problems.append(f"{var} is sentinel/absent locally")
    return (not problems, problems)


# --- SSM read-back (presence + is-sentinel, NO value printing) ---------------


def _ssm_state(param: str, region: str) -> str:
    """One of: 'real' | 'sentinel' | 'empty' | 'missing'. Never prints value.

    Fetches with decryption so we can compare to the sentinel locally, then
    drops the value. The value never leaves this function.
    """
    try:
        out = subprocess.run(
            [
                "aws",
                "ssm",
                "get-parameter",
                "--name",
                f"{SSM_PREFIX}/{param}",
                "--with-decryption",
                "--region",
                region,
                "--output",
                "text",
                "--query",
                "Parameter.Value",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return f"error:{type(exc).__name__}"
    if out.returncode != 0:
        # ParameterNotFound (or perms). Treat not-found as missing; surface other
        # errors distinctly without leaking anything sensitive.
        if "ParameterNotFound" in out.stderr:
            return "missing"
        return "error:aws"
    value = out.stdout.rstrip("\n")
    if value == SENTINEL:
        return "sentinel"
    if value == "":
        return "empty"
    return "real"  # value intentionally dropped here; never returned/printed


def _ssm_vars_for(p: Provider) -> list[str]:
    return list(p.required) + list(p.optional)


# --- Live OKX news ping (secret-safe; status + okx code only) ----------------


def _okx_news_ping() -> str:
    import base64
    import hashlib
    import hmac
    from datetime import UTC, datetime

    import httpx

    key, secret = _clean("OKX_TRADING_API_KEY"), _clean("OKX_TRADING_SECRET_KEY")
    passphrase = _clean("OKX_TRADING_PASSPHRASE")
    if not key or not secret:
        return "skip (key/secret not both set locally)"
    host = "https://www.okx.com"
    path = "/api/v5/orbit/news-search?ccyList=BTC&sortBy=latest&limit=1"
    now = datetime.now(tz=UTC)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    sign = base64.b64encode(
        hmac.new(secret.encode(), f"{ts}GET{path}".encode(), hashlib.sha256).digest()
    ).decode()
    headers = {
        "OK-ACCESS-KEY": key,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "Content-Type": "application/json",
    }
    if passphrase:
        headers["OK-ACCESS-PASSPHRASE"] = passphrase
    try:
        r = httpx.get(host + path, headers=headers, timeout=15.0)
    except Exception as exc:
        return f"ERROR {type(exc).__name__}"
    try:
        body = r.json()
        code = body.get("code") if isinstance(body, dict) else None
        msg = body.get("msg") if isinstance(body, dict) else None
    except Exception:
        code, msg = None, None
    ok = r.status_code == 200 and str(code) == "0"
    mark = "OK" if ok else "FAIL"
    return f"{mark} http={r.status_code} okx_code={code} okx_msg={msg!r}"


# --- Main --------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-deploy config-parity preflight.")
    ap.add_argument("--check-ssm", action="store_true", help="diff local env vs SSM (read-back)")
    ap.add_argument("--ping", action="store_true", help="live OKX news auth ping (status only)")
    ap.add_argument("--region", default=os.environ.get("AWS_DEFAULT_REGION", "us-east-2"))
    args = ap.parse_args()

    providers = _discover_providers()
    enabled = [p for p in providers if p.enabled]

    print("=== Preflight config-parity ===")
    print(f"region={args.region}  check_ssm={args.check_ssm}  ping={args.ping}")
    print(f"enabled providers: {[p.name for p in enabled] or 'NONE'}")
    print("")

    failures: list[str] = []

    for p in enabled:
        ok, problems = _local_status(p)
        status = "OK " if ok else "BAD"
        print(f"[{status}] {p.name}  (LOCAL)")
        print(f"        {p.note}")
        for prob in problems:
            print(f"        - LOCAL: {prob}")
            failures.append(f"{p.name}: {prob}")

        if args.check_ssm:
            for var in _ssm_vars_for(p):
                local = "real" if _clean(var) else "sentinel/absent"
                remote = _ssm_state(var, args.region)
                print(f"        SSM  {var}: local={local}  ssm={remote}")
                required = var in p.required
                # Drift = configured locally but NOT real in SSM. This is the
                # exact failure mode that left OKX news dark.
                if _clean(var) and remote != "real":
                    sev = "REQUIRED" if required else "optional"
                    msg = f"{p.name}: {var} is real LOCALLY but '{remote}' in SSM ({sev})"
                    print(f"        !! DRIFT ({sev}): {var} local-real / ssm-{remote}")
                    # Only required-cred drift fails the gate; optional drift warns.
                    if required:
                        failures.append(msg)
            # solana-rpc special: at least one of the two must be real in SSM.
            if p.name == "solana-rpc":
                states = {v: _ssm_state(v, args.region) for v in p.optional}
                if "real" not in states.values():
                    failures.append(
                        "solana-rpc: neither HELIUS_API_KEY nor QUICKNODE_RPC_URL is real in SSM"
                    )
                    print("        !! DRIFT (REQUIRED): no Solana RPC cred is real in SSM")
        print("")

    if args.ping and any(p.name == "okx-news" for p in enabled):
        print("=== OKX news live auth ping (secret-safe) ===")
        print(f"  {_okx_news_ping()}")
        print("")

    if failures:
        print("PREFLIGHT FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(
        "PREFLIGHT PASSED — all enabled providers provisioned (local"
        + (" + SSM)" if args.check_ssm else ").")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
