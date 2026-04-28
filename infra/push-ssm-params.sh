#!/usr/bin/env bash
# =============================================================
# Push gecko-api secrets/config from a local .env (or environment) into AWS
# SSM Parameter Store as SecureString. Values are never printed — only the
# parameter name and result status.
#
# Usage:
#   ./infra/push-ssm-params.sh [--region us-east-2] [--env-file .env]
#
# Switching networks (devnet ↔ mainnet) post-deploy:
#   aws ssm put-parameter --name /gecko-api/X402_NETWORK \
#     --value 'solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp' \
#     --type SecureString --overwrite --region us-east-2
#   aws ecs update-service --cluster gecko-api --service gecko-api \
#     --force-new-deployment --region us-east-2
# =============================================================
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-us-east-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

while [[ $# -gt 0 ]]; do
  case $1 in
    --region)   REGION="$2";   shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: env file '$ENV_FILE' not found" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

SSM_PREFIX="/gecko-api"

# All gecko-api secrets/config in one place. SSM param name on the left,
# shell variable name on the right (so we can rename params without renaming
# our env vars). Every value goes in as SecureString — there's no harm in
# encrypting non-secret config too, and it keeps the deploy uniform.
declare -A PARAMS=(
  # Database / external APIs
  [SUPABASE_URL]="SUPABASE_URL"
  [SUPABASE_SERVICE_ROLE_KEY]="SUPABASE_SERVICE_ROLE_KEY"
  [TAVILY_API_KEY]="TAVILY_API_KEY"
  [OPENAI_API_KEY]="OPENAI_API_KEY"
  [DEEPGRAM_API_KEY]="DEEPGRAM_API_KEY"

  # x402 (devnet ↔ mainnet via SSM update + force-new-deployment)
  [X402_MODE]="X402_MODE"
  [X402_NETWORK]="X402_NETWORK"
  [X402_FACILITATOR_URL]="X402_FACILITATOR_URL"
  [GECKO_WALLET_ADDRESS]="GECKO_WALLET_ADDRESS"
  [RESEARCH_BASIC_PRICE]="RESEARCH_BASIC_PRICE"
  [RESEARCH_PRO_PRICE]="RESEARCH_PRO_PRICE"

  # LLM endpoint
  [GECKO_LLM_ENDPOINT]="GECKO_LLM_ENDPOINT"
  [GECKO_LLM_API_KEY]="GECKO_LLM_API_KEY"
  [CHAT_MODEL]="CHAT_MODEL"
)

echo "==> Region:     $REGION"
echo "==> SSM prefix: $SSM_PREFIX"
echo "==> Env file:   $ENV_FILE"
echo ""

SKIPPED=()
PUSHED=()

for PARAM_NAME in "${!PARAMS[@]}"; do
  VAR_NAME="${PARAMS[$PARAM_NAME]}"
  VALUE="${!VAR_NAME:-}"

  if [[ -z "$VALUE" ]]; then
    echo "  SKIP  $SSM_PREFIX/$PARAM_NAME  (${VAR_NAME} is empty in $ENV_FILE)"
    SKIPPED+=("$PARAM_NAME")
    continue
  fi

  aws ssm put-parameter \
    --name "${SSM_PREFIX}/${PARAM_NAME}" \
    --value "$VALUE" \
    --type SecureString \
    --overwrite \
    --region "$REGION" \
    --output text \
    --query 'Version' \
    | xargs -I{} echo "  OK    $SSM_PREFIX/$PARAM_NAME  (version {})"

  PUSHED+=("$PARAM_NAME")
done

echo ""
echo "==> Done. ${#PUSHED[@]} pushed, ${#SKIPPED[@]} skipped."

if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo ""
  echo "Skipped (fill in $ENV_FILE and re-run):"
  for P in "${SKIPPED[@]}"; do
    echo "  - $SSM_PREFIX/$P"
  done
fi

echo ""
echo "Quick reference for two big knobs:"
echo "  X402_NETWORK=solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1   # devnet"
echo "  X402_NETWORK=solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp   # mainnet-beta"
echo "  RESEARCH_BASIC_PRICE='\$0.10'                           # devnet test"
echo "  RESEARCH_BASIC_PRICE='\$0.50'                           # mainnet starter"
echo "  RESEARCH_BASIC_PRICE='\$20.00'                          # production target"
