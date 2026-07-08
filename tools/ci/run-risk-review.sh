#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------------
# run-risk-review.sh — Run the OpenCode Renovate risk classifier via CLI
#
# Expectations (must be satisfied by the workflow before this step):
#   - .review/context.json exists (built by build-renovate-review-context.sh)
#   - OPENCODE_API_KEY is set in the environment
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE=".github/prompts/renovate-dependency-risk-review.md"
CONTEXT_JSON=".review/context.json"
PROMPT_FILE=".review/opencode-prompt.md"
RAW_OUTPUT=".review/opencode-result.raw"
RESULT_JSON=".review/opencode-result.json"

MODEL="${OPENCODE_MODEL:-opencode/deepseek-v4-flash}"
AGENT_DIR=".opencode/agents"
AGENT_NAME="renovate-risk-classifier"

# --- 1. Guard: required inputs ------------------------------------------------
if [[ ! -f "$PROMPT_TEMPLATE" ]]; then
  echo "ERROR: prompt template not found at $PROMPT_TEMPLATE" >&2
  exit 2
fi
if [[ ! -f "$CONTEXT_JSON" ]]; then
  echo "ERROR: context not found at $CONTEXT_JSON — run build-renovate-review-context.sh first" >&2
  exit 2
fi

mkdir -p .review "$AGENT_DIR"

# --- 2. Create a read-only OpenCode agent -------------------------------------
# Model is controlled via the CLI --model flag (OPENCODE_MODEL env var), not here.
cat > "$AGENT_DIR/$AGENT_NAME.md" <<'AGENT_EOF'
---
description: Classifies Renovate dependency PR risk without modifying files
mode: primary
temperature: 0.1
permission:
  edit: deny
  bash: deny
---
You are a deterministic dependency risk classifier.
Do not modify files.
Do not run commands.
Return only the requested JSON object.
AGENT_EOF

# --- 3. Assemble the prompt ---------------------------------------------------
{
  cat "$PROMPT_TEMPLATE"
  echo
  echo "## PR context"
  cat "$CONTEXT_JSON"
  echo
  echo "Return only valid JSON. No Markdown. No prose."
} > "$PROMPT_FILE"

# --- 4. Run OpenCode (non-interactive) ----------------------------------------
set +e
opencode run \
  --agent "$AGENT_NAME" \
  --model "$MODEL" \
  --title "Renovate dependency risk review" \
  < "$PROMPT_FILE" \
  > "$RAW_OUTPUT"
OPENCODE_EXIT=$?
set -e

# --- 5. Extract JSON (falls back to neutral on failure) -----------------------
python3 tools/ci/extract-risk-json.py "$RAW_OUTPUT" "$RESULT_JSON"

if [[ "$OPENCODE_EXIT" -ne 0 ]]; then
  echo "OpenCode exited with $OPENCODE_EXIT — review may have fallen back to neutral." >&2
fi
