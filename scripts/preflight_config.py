"""LOCAL preflight config-parity check — run BEFORE every deploy.

WHY THIS EXISTS (the bug it catches): OKX news went DARK in prod because
``infra/push-ssm-params.sh`` errored mid-run and never pushed
``OKX_TRADING_SECRET_KEY`` + ``OKX_TRADING_PASSPHRASE`` to SSM. Locally
everything worked (the creds were in ``.env``); prod got a partial credential
set => OKX returned HTTP 401 => the adapter fail-OPENed to ``[]`` => silent dark
wedge. The class of bug is "works locally but missing/wrong in PRD" — a
local≠SSM config drift. This script catches it before the deploy, not after.

PROVIDER LIST IS DATA, NOT CODE. The set of providers, their enabled-conditions,
and required creds live in ``infra/secrets-manifest.yml`` — the single source of
truth shared with the gecko-api boot banner and the parity drift test. This
script READS the manifest via :mod:`gecko_core.config.provider_status`; adding a
provider is a manifest edit, never a code edit here.

WHAT IT DOES, per ENABLED provider (enabled per the manifest ``enabled_when``):
  1. LOCAL check — assert every required cred is present + non-sentinel in the
     loaded environment (``.env`` via ``set -a; source .env``). ``resolve_all``
     does this and returns LIVE / DARK / disabled per provider.
  2. SSM check (``--check-ssm``) — read back each required cred's SSM param via
     the ``aws`` CLI (presence + is-sentinel ONLY, value never fetched-then-
     printed) and DIFF local-has vs SSM-has. Any cred real locally but
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

EXIT CODE: non-zero if any enabled provider is DARK locally (a required cred is
sentinel/missing) or (with --check-ssm) drifts between local and SSM. Wire it
into a pre-deploy gate.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Make gecko-core importable when this script is run with `uv run python` from
# the repo root (uv resolves the workspace) — no path hacking needed there. The
# explicit insert keeps a bare `python scripts/preflight_config.py` working too.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_SRC = _REPO_ROOT / "packages" / "gecko-core" / "src"
if _CORE_SRC.is_dir() and str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))

from typing import Any  # noqa: E402

from gecko_core.config.provider_status import (  # noqa: E402
    SENTINEL,
    ProviderStatus,
    _is_real,
    resolve_all,
)

SSM_PREFIX = "/gecko-api"
_MANIFEST = _REPO_ROOT / "infra" / "secrets-manifest.yml"


def _manifest_providers() -> dict[str, dict[str, Any]]:
    import yaml

    data = yaml.safe_load(_MANIFEST.read_text())
    providers: dict[str, dict[str, Any]] = data["providers"]
    return providers


def _required_vars(name: str, providers: dict[str, dict[str, Any]]) -> list[str]:
    """All cred env-vars worth checking in SSM for a provider (required + any-of)."""
    spec = providers.get(name, {})
    vars_: list[str] = list(spec.get("requires") or [])
    vars_ += list(spec.get("requires_any_of") or [])
    return vars_


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
        if "ParameterNotFound" in out.stderr:
            return "missing"
        return "error:aws"
    value = out.stdout.rstrip("\n")
    if value == SENTINEL:
        return "sentinel"
    if value == "":
        return "empty"
    return "real"  # value intentionally dropped here; never returned/printed


# --- Live OKX news ping (secret-safe; status + okx code only) ----------------


def _okx_news_ping() -> str:
    import base64
    import hashlib
    import hmac
    from datetime import UTC, datetime

    import httpx

    key = os.environ.get("OKX_TRADING_API_KEY", "").strip()
    secret = os.environ.get("OKX_TRADING_SECRET_KEY", "").strip()
    passphrase = os.environ.get("OKX_TRADING_PASSPHRASE", "").strip()
    key = "" if key == SENTINEL else key
    secret = "" if secret == SENTINEL else secret
    passphrase = "" if passphrase == SENTINEL else passphrase
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

    providers_spec = _manifest_providers()
    statuses: list[ProviderStatus] = resolve_all(_MANIFEST)
    enabled = [s for s in statuses if s.enabled]

    print("=== Preflight config-parity (manifest-driven) ===")
    print(f"manifest={_MANIFEST.relative_to(_REPO_ROOT)}")
    print(f"region={args.region}  check_ssm={args.check_ssm}  ping={args.ping}")
    print(f"enabled providers: {[s.name for s in enabled] or 'NONE'}")
    print("")

    failures: list[str] = []

    for s in enabled:
        local_ok = s.status == "LIVE"
        tag = "OK " if local_ok else "DARK"
        print(f"[{tag}] {s.name}  (LOCAL)  fail_mode={s.fail_mode}")
        print(f"        {s.reason}")
        if not local_ok:
            failures.append(f"{s.name}: {s.reason}")

        if args.check_ssm:
            for var in _required_vars(s.name, providers_spec):
                local = "real" if _is_real(var) else "sentinel/absent"
                remote = _ssm_state(var, args.region)
                print(f"        SSM  {var}: local={local}  ssm={remote}")
                # Drift = real locally but NOT real in SSM. The exact failure
                # mode that left OKX news dark.
                if _is_real(var) and remote != "real":
                    print(f"        !! DRIFT: {var} local-real / ssm-{remote}")
                    failures.append(f"{s.name}: {var} is real LOCALLY but '{remote}' in SSM")
        print("")

    if args.ping and any(s.name == "okx_news" for s in enabled):
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
