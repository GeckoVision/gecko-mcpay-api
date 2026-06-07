#!/usr/bin/env bash
# =============================================================================
# infra/push-agent-ssm-params.sh — push the /gecko-agent SSM params consumed by
# ecs-agent-stack.yml. Self-contained (separate from push-ssm-params.sh, which
# owns /gecko-api). Reads values from repo-root .env. Founder-run (touches AWS).
#
# Usage:  ./infra/push-agent-ssm-params.sh [--region us-east-2]
# =============================================================================
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-2}"
while [[ $# -gt 0 ]]; do
  case $1 in
    --region) REGION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

PREFIX="/gecko-agent"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$(cd "$SCRIPT_DIR/.." && pwd)/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a; # shellcheck disable=SC1090
  source "$ENV_FILE"; set +a
fi

put () {  # name value type
  aws ssm put-parameter --name "$PREFIX/$1" --value "$2" --type "$3" --overwrite --region "$REGION" >/dev/null \
    && echo "  set $PREFIX/$1"
}

echo "==> pushing $PREFIX params (region $REGION)"
put MONGODB_URI        "${MONGODB_URI:?set MONGODB_URI in .env}"        SecureString
put MONGODB_DB         "${MONGODB_DB:-gecko}"                            String
put OPENROUTER_API_KEY "${OPENROUTER_API_KEY:?set OPENROUTER_API_KEY in .env}" SecureString
put LLM_ROUTER         "openrouter"                                      String
echo "==> done."
