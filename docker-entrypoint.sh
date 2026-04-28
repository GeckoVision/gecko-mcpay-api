#!/bin/sh
# Entry point for the gecko-api ECS task.
#
# Settings.from_env() reads X402_MODE, X402_FACILITATOR_URL, X402_NETWORK,
# GECKO_WALLET_ADDRESS, RESEARCH_BASIC_PRICE, RESEARCH_PRO_PRICE at module
# import time. ECS injects them as plain env vars (sourced from SSM by the
# task definition's `secrets` block), so by the time uvicorn imports
# gecko_api.main everything is already in os.environ.
set -e

# Bind to 0.0.0.0 inside the container so the ALB can reach us.
exec uvicorn gecko_api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips='*'
