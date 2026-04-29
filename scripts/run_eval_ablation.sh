#!/usr/bin/env bash
# Eval-bias-fix ablation harness.
#
# Three sequential live runs against the general suite that isolate where
# the v5.4 verdict_accuracy=1.0 came from before the bias fix landed:
#
#   Run A: v5.4 prompt + judge=gpt-4o-mini + LEAKY rag_context
#          (baseline reference — reproduces the original 1.0 reading)
#   Run B: v5.4 prompt + judge=gpt-4o + STRIPPED rag_context
#          (production-shaped — this is the gate's real number)
#   Run C: v5.3 prompt + judge=gpt-4o + STRIPPED rag_context
#          (isolates the v5.3->v5.4 prompt-diff lift)
#
# Run A requires the pre-fix leaky fixtures. We snapshot them from git
# (the commit just before this script lands) into a tmp tree, point the
# runner at it via GECKO_EVAL_SUITES_DIR, and restore on exit. If that
# env var is not honored by the runner in your branch, Run A degrades
# gracefully to "use whatever fixtures are on disk" with a warning — the
# B and C numbers are the load-bearing ones.
#
# Usage:
#   ./scripts/run_eval_ablation.sh
#
# Requires:
#   OPENAI_API_KEY, ANTHROPIC_API_KEY (or CLAUDE_API_KEY)
#
# Cost: ~$3 total. Runtime: ~15 minutes sequential.
#
# See: docs/runbooks/eval-bias-fix.md

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIVE_RUNS_DIR="${ROOT_DIR}/tests/eval/live_runs"
SUITE="general"
RERUNS="${GECKO_EVAL_RERUNS:-1}"

cd "${ROOT_DIR}"

# --- 1. Env preconditions ----------------------------------------------------

: "${OPENAI_API_KEY:?OPENAI_API_KEY must be set (5 AG2 agents need it)}"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY (or CLAUDE_API_KEY) must be set for the rubric judge." >&2
  exit 2
fi

cat <<EOF

================================================================
  Eval-bias-fix ablation
================================================================

  Suite:         ${SUITE} (20 ideas)
  Reruns/idea:   ${RERUNS}
  Mode:          --live
  Total budget:  ~\$3 / ~15 min sequential

  Run A: v5.4 + judge=gpt-4o-mini + LEAKY fixtures (baseline reference)
  Run B: v5.4 + judge=gpt-4o      + STRIPPED fixtures (real gate number)
  Run C: v5.3 + judge=gpt-4o      + STRIPPED fixtures (prompt-diff lift)

EOF

read -r -p "Proceed? Type 'y' to continue: " CONFIRM
if [ "${CONFIRM}" != "y" ] && [ "${CONFIRM}" != "Y" ]; then
  echo "Aborted."
  exit 1
fi

today="$(date -u +%Y-%m-%d)"

# --- 2. Stage leaky fixtures from git for Run A ------------------------------
#
# We restore the suite file from the commit just prior to the bias-fix
# commit. If it can't be located (e.g. running this on a fresh checkout
# without that history), Run A is skipped with a warning.

LEAKY_TMP="$(mktemp -d)"
trap 'rm -rf "${LEAKY_TMP}"' EXIT

LEAKY_REF="$(git log --diff-filter=M --format='%H' -1 -- tests/eval/suites/${SUITE}_suite.json | sed -n '2p' || true)"
LEAKY_AVAILABLE=0
if [ -n "${LEAKY_REF}" ]; then
  if git show "${LEAKY_REF}:tests/eval/suites/${SUITE}_suite.json" > "${LEAKY_TMP}/${SUITE}_suite.json" 2>/dev/null; then
    LEAKY_AVAILABLE=1
  fi
fi

# --- helpers -----------------------------------------------------------------

_acc_of() {
  python3 -c "import json,sys; print(json.load(open('$1'))['aggregate']['verdict_accuracy'])"
}

_latest_live() {
  ls -1t "${LIVE_RUNS_DIR}/${today}-${SUITE}"*.json 2>/dev/null | head -n 1 || true
}

_run() {
  # _run <label> <prompts_version> <extra-env-key=value...>
  local label="$1"; shift
  local pv="$1"; shift
  echo
  echo "=== ${label} (prompts=${pv}) ==="
  env "$@" GECKO_PRO_PROMPTS_VERSION="${pv}" \
    uv run python -m tests.eval.runner \
      --suite "${SUITE}" --live --reruns "${RERUNS}" \
      --prompts-version "${pv}"
}

# --- 3. Run A: v5.4 + leaky fixtures + judge=gpt-4o-mini ---------------------
#
# We swap in leaky fixtures via a temporary suites dir, then run with
# GECKO_JUDGE_MODEL=gpt-4o-mini to suppress the live runner's default
# judge=gpt-4o override. If the runner doesn't honor either env var on
# this branch, the resulting number is still a valid "v5.4 with whatever
# is on disk" reading — note that in the writeup.

ACC_A=""
RUNFILE_A=""
if [ "${LEAKY_AVAILABLE}" -eq 1 ]; then
  ABLATION_SUITES_DIR="${LEAKY_TMP}"
  cp -f "${ROOT_DIR}/tests/eval/suites/crypto_suite.json" "${ABLATION_SUITES_DIR}/" 2>/dev/null || true
  cp -f "${ROOT_DIR}/tests/eval/suites/saas_suite.json" "${ABLATION_SUITES_DIR}/" 2>/dev/null || true
  _run "Run A: v5.4 + leaky + 4o-mini judge" "v5.4" \
    GECKO_EVAL_SUITES_DIR="${ABLATION_SUITES_DIR}" \
    GECKO_JUDGE_MODEL="gpt-4o-mini"
else
  echo "WARN: cannot locate prior leaky fixtures in git history; Run A will use on-disk (stripped) fixtures."
  _run "Run A: v5.4 + (on-disk) + 4o-mini judge" "v5.4" \
    GECKO_JUDGE_MODEL="gpt-4o-mini"
fi
RUNFILE_A="$(_latest_live)"
ACC_A="$(_acc_of "${RUNFILE_A}")"

# --- 4. Run B: v5.4 + stripped fixtures + judge=gpt-4o (default) -------------

_run "Run B: v5.4 + stripped + 4o judge" "v5.4"
RUNFILE_B="$(_latest_live)"
ACC_B="$(_acc_of "${RUNFILE_B}")"

# --- 5. Run C: v5.3 + stripped fixtures + judge=gpt-4o (default) -------------

_run "Run C: v5.3 + stripped + 4o judge" "v5.3"
RUNFILE_C="$(_latest_live)"
ACC_C="$(_acc_of "${RUNFILE_C}")"

# --- 6. Summary --------------------------------------------------------------

echo
echo "================================================================"
echo "  Eval-bias-fix ablation results (suite=${SUITE})"
echo "================================================================"
printf "  %-50s %s\n" "Run A (v5.4 + leaky + 4o-mini judge)" "verdict_accuracy=${ACC_A}"
printf "  %-50s %s\n" "Run B (v5.4 + stripped + 4o judge)" "verdict_accuracy=${ACC_B}"
printf "  %-50s %s\n" "Run C (v5.3 + stripped + 4o judge)" "verdict_accuracy=${ACC_C}"
echo
DELTA_AB="$(python3 -c "print(round(float('${ACC_A}') - float('${ACC_B}'), 3))")"
DELTA_BC="$(python3 -c "print(round(float('${ACC_B}') - float('${ACC_C}'), 3))")"
echo "  Leakage lift (A - B): ${DELTA_AB}"
echo "  Prompt-diff lift (B - C): ${DELTA_BC}"
echo
echo "  Interpretation:"
echo "    - A ~ 1.0 + B << 1.0  =>  pre-fix gate was measuring fixture leakage."
echo "    - B - C  >  0         =>  v5.4 prompt is a real lift over v5.3."
echo "    - B - C  ~ 0          =>  v5.4 lift was leakage-driven; reopen prompt work."
echo
echo "  Run files:"
echo "    A: ${RUNFILE_A}"
echo "    B: ${RUNFILE_B}"
echo "    C: ${RUNFILE_C}"
