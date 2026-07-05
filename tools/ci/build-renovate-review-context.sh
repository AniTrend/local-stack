#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

PR_JSON=".review/pr.json"
FILES_TXT=".review/files.txt"
CONTEXT_JSON=".review/context.json"

if [[ ! -f "$PR_JSON" ]]; then
  echo "ERROR: $PR_JSON not found. Run the 'Collect PR changed files' step first." >&2
  exit 1
fi

if [[ ! -f "$FILES_TXT" ]]; then
  echo "ERROR: $FILES_TXT not found. Run the 'Collect PR changed files' step first." >&2
  exit 1
fi

echo "Building review context from $PR_JSON and $FILES_TXT..."

# Convert plain-text file list to a JSON array for safe jq handling
CHANGED_FILES_JSON=$(jq -R -s 'split("\n") | map(select(length > 0))' "$FILES_TXT")

jq -n \
  --slurpfile pr "$PR_JSON" \
  --argjson changed_files "$CHANGED_FILES_JSON" \
  '{
    pr: $pr[0],
    changed_files: $changed_files
  }' > "$CONTEXT_JSON"

echo "Review context written to $CONTEXT_JSON"
