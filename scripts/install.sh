#!/usr/bin/env bash
# =============================================================================
# Gecko one-line installer (pre-PyPI)
#
#   curl -fsSL https://app.geckovision.tech/install.sh | bash
#
# What this does:
#   1. Verifies prereqs (Python 3.11+, uv, optionally Node 18+ for ClawRouter,
#      and the Claude Code CLI).
#   2. Installs `gecko-mcp` via `uv tool install` directly from the GitHub
#      subdirectory until the package is published to PyPI.
#   3. Registers the MCP server with Claude Code (best-effort).
#   4. Prints next steps — wallet connection (frames.ag), then a research call.
#
# Flags:
#   --no-mcp-register   Skip the `claude mcp add` step.
#   --ref <branch|tag>  Install from a specific git ref. Default: main.
#   --repo <url>        Override the GitHub URL (private fork, etc.).
#
# Pinned env (override before piping):
#   GECKO_MCP_REPO    — full git URL (default: GitHub canonical)
#   GECKO_MCP_REF     — ref to install (default: main)
# =============================================================================
set -euo pipefail

GECKO_MCP_REPO="${GECKO_MCP_REPO:-https://github.com/geckovision/gecko-mcpay-api.git}"
GECKO_MCP_REF="${GECKO_MCP_REF:-main}"
SKIP_MCP_REGISTER=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-mcp-register) SKIP_MCP_REGISTER=true; shift ;;
    --ref)             GECKO_MCP_REF="$2"; shift 2 ;;
    --repo)            GECKO_MCP_REPO="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 2 ;;
  esac
done

c_red()    { printf "\033[31m%s\033[0m" "$*"; }
c_green()  { printf "\033[32m%s\033[0m" "$*"; }
c_yellow() { printf "\033[33m%s\033[0m" "$*"; }
c_bold()   { printf "\033[1m%s\033[0m" "$*"; }

ok()    { echo "  $(c_green ✅) $*"; }
warn()  { echo "  $(c_yellow ⚠️ ) $*"; }
fail()  { echo "  $(c_red ❌) $*"; }

hdr()   { echo; echo "$(c_bold "▶ $*")"; }

# -----------------------------------------------------------------------------

hdr "1/4 Prereqs"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found — install Python 3.11+ first"
  exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
PY_MAJOR="$(echo "$PY_VERSION" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VERSION" | cut -d. -f2)"
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 11 ]]; }; then
  fail "Python 3.11+ required (found $PY_VERSION)"
  exit 1
fi
ok "Python $PY_VERSION"

if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # uv installs to ~/.local/bin which may not be on PATH yet
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"

if command -v node >/dev/null 2>&1; then
  ok "node $(node --version) — ClawRouter can self-start"
else
  warn "node not found — ClawRouter won't auto-start. Install Node 18+ to enable the v3 LLM path"
  warn "  (workaround: set GECKO_LLM_ENDPOINT=https://api.openai.com/v1 + GECKO_LLM_API_KEY=...)"
fi

if command -v claude >/dev/null 2>&1; then
  ok "Claude Code CLI present"
  HAVE_CLAUDE=true
else
  warn "Claude Code CLI not found — MCP registration will be skipped"
  HAVE_CLAUDE=false
fi

# -----------------------------------------------------------------------------

hdr "2/4 Install gecko-mcp"

UV_PACKAGE="git+${GECKO_MCP_REPO}@${GECKO_MCP_REF}#subdirectory=packages/gecko-mcp"
echo "  source: $UV_PACKAGE"
uv tool install --force "$UV_PACKAGE"
ok "gecko-mcp installed"

# -----------------------------------------------------------------------------

hdr "3/4 Register with Claude Code"

if [[ "$SKIP_MCP_REGISTER" == "true" ]] || [[ "$HAVE_CLAUDE" == "false" ]]; then
  warn "skipped (run manually: claude mcp add gecko -- gecko-mcp serve)"
else
  if claude mcp list 2>/dev/null | grep -q '^gecko'; then
    ok "gecko already registered"
  else
    claude mcp add gecko -- gecko-mcp serve >/dev/null
    ok "gecko registered with Claude Code"
  fi
fi

# -----------------------------------------------------------------------------

hdr "4/4 Next steps"

cat <<'EOF'

  Connect your wallet (paste this into Claude Code):

      Read https://frames.ag/skill.md and follow the instructions
      to join AgentWallet.

  Verify everything is up:

      gecko-mcp quickstart

  Run your first session (in Claude Code):

      Use gecko_research to validate: a hotel guide for Brazil

  Inspect the receipts:

      gecko-mcp economics <session_id>

  Builder Bootstrap Platform · geckovision.tech · No API keys, just a wallet.
EOF
