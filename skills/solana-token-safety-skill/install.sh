#!/usr/bin/env bash
# Install the solana-token-safety skill into a Claude Code / Codex agent config.
#
# Safe + minimal: it only COPIES markdown files (the skill + the command) into
# your agent's skills directory. No binaries, no network calls, nothing opaque.
# The skill itself calls the free, keyless Gecko /safety endpoint at runtime.
#
# Usage:
#   bash install.sh                     # install to ~/.claude
#   CLAUDE_DIR=/path/to/cfg bash install.sh   # install to a custom config dir
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CLAUDE_DIR:-$HOME/.claude}"
SKILL_NAME="solana-token-safety"

echo "==> Installing the ${SKILL_NAME} skill into ${DEST}"

mkdir -p "${DEST}/skills/${SKILL_NAME}" "${DEST}/commands" "${DEST}/agents" "${DEST}/rules"

# 1) The skill (SKILL.md + focused .md routing files + examples)
cp -R "${SRC_DIR}/skill/." "${DEST}/skills/${SKILL_NAME}/"
cp -R "${SRC_DIR}/examples" "${DEST}/skills/${SKILL_NAME}/examples"
echo "    • skill    -> ${DEST}/skills/${SKILL_NAME}/"

# 2) Commands (/safety-check, /launch-check)
cp "${SRC_DIR}/commands/"*.md "${DEST}/commands/"
echo "    • commands -> ${DEST}/commands/ (safety-check, launch-check)"

# 3) Agent persona (token-safety-auditor)
cp "${SRC_DIR}/agents/"*.md "${DEST}/agents/"
echo "    • agent    -> ${DEST}/agents/token-safety-auditor.md"

# 4) Pre-trade rule (opt-in)
cp "${SRC_DIR}/rules/"*.md "${DEST}/rules/"
echo "    • rule     -> ${DEST}/rules/pre-trade-safety.md"

cat <<'EOF'

==> Done.

Use it:
  • Ask your agent: "is this token safe to trade: <mint>?"
  • Or run the command: /safety-check <mint>

It calls the free, keyless Gecko /safety oracle. No API key required.
For agent pre-trade integration, see skill/agent-integration.md.
EOF
