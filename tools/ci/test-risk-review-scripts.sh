#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# test-risk-review-scripts.sh — Run extractor and validator fixture tests
#
# Usage: bash tools/ci/test-risk-review-scripts.sh
#
# Requires: Python 3, pip packages from tools/requirements.txt installed.
# ---------------------------------------------------------------------------
set -euo pipefail
IFS=$'\n\t'

PASSED=0
FAILED=0
EXTRACTOR=(python3 tools/ci/extract-risk-json.py)
VALIDATOR=(python3 tools/ci/validate-opencode-risk-output.py)
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# --- Helpers ------------------------------------------------------------------

pass() {
  printf "  [\033[32mPASS\033[0m] %s\n" "$1"
  PASSED=$((PASSED + 1))
}

fail() {
  printf "  [\033[31mFAIL\033[0m] %s\n" "$1"
  if [[ $# -gt 1 ]]; then
    printf "         %s\n" "$2"
  fi
  FAILED=$((FAILED + 1))
}

# Run the extractor then the validator. Both should succeed.
run_extraction_test() {
  local label="$1" input="$2"
  local out="$TMPDIR/extracted.json"
  if "${EXTRACTOR[@]}" "$input" "$out" > /dev/null 2>&1; then
    if "${VALIDATOR[@]}" "$out" > /dev/null 2>&1; then
      pass "$label"
    else
      fail "$label" "validator rejected extracted JSON"
    fi
  else
    fail "$label" "extractor failed"
  fi
}

# Run the validator only. Report pass when it exits 0, fail when it exits non-0.
run_validator_expected_pass() {
  local label="$1" input="$2"
  if "${VALIDATOR[@]}" "$input" > /dev/null 2>&1; then
    pass "$label"
  else
    fail "$label" "validator unexpectedly rejected"
  fi
}

# Run the validator only. Report pass when it exits non-0 (correctly rejected).
run_validator_expected_fail() {
  local label="$1" input="$2" expected_msg="$3"
  if ! "${VALIDATOR[@]}" "$input" >/dev/null 2>&1; then
    pass "$label"
  else
    fail "$label" "$expected_msg"
  fi
}

# --- Extractor tests ----------------------------------------------------------

echo "--- Extractor tests ---"

run_extraction_test \
  "plain JSON" \
  fixtures/opencode/raw-plain-json.txt

run_extraction_test \
  "markdown-fenced JSON" \
  fixtures/opencode/raw-markdown-fenced-json.txt

run_extraction_test \
  "ANSI-prefixed JSON" \
  fixtures/opencode/raw-ansi-prefixed-json.txt

run_extraction_test \
  "no JSON → neutral fallback" \
  fixtures/opencode/raw-no-json.txt

run_extraction_test \
  "wrong schema → neutral fallback" \
  fixtures/opencode/raw-wrong-schema.txt

# --- Validator: expected pass ------------------------------------------------

echo "--- Validator tests (expected PASS) ---"

run_validator_expected_pass \
  "valid approve" \
  fixtures/opencode/valid-approve.json

# Neutral fallback must pass the hardened validator
if "${EXTRACTOR[@]}" fixtures/opencode/raw-no-json.txt "$TMPDIR/fallback.json" >/dev/null 2>&1; then
  run_validator_expected_pass \
    "neutral fallback passes validator" \
    "$TMPDIR/fallback.json"
else
  fail "neutral fallback passes validator" "extractor could not produce fallback"
fi

# --- Validator: expected fail ------------------------------------------------

echo "--- Validator tests (expected FAIL) ---"

run_validator_expected_fail \
  "neutral + automerge=true" \
  fixtures/opencode/invalid-neutral-automerge.json \
  "should reject automerge with neutral decision"

run_validator_expected_fail \
  "changes_requested + automerge=true" \
  fixtures/opencode/invalid-changes-automerge.json \
  "should reject automerge with changes_requested decision"

run_validator_expected_fail \
  "major + automerge=true" \
  fixtures/opencode/invalid-major-automerge.json \
  "should reject automerge for semver-major"

run_validator_expected_fail \
  "invalid confidence enum" \
  fixtures/opencode/invalid-confidence-enum.json \
  "should reject invalid confidence value"

run_validator_expected_fail \
  "changed_files as string" \
  fixtures/opencode/invalid-list-as-string.json \
  "should reject non-array changed_files"

run_validator_expected_fail \
  "approve + risk=medium" \
  fixtures/opencode/invalid-approve-medium-risk.json \
  "should reject approve with risk != low"

run_validator_expected_fail \
  "approve + update_type=semver-major" \
  fixtures/opencode/invalid-approve-major-update.json \
  "should reject approve with semver-major update"

run_validator_expected_fail \
  "approve + github-actions major" \
  fixtures/opencode/invalid-approve-gh-actions-major.json \
  "should reject approve for github-actions major update"

run_validator_expected_fail \
  "approve + workflow file change" \
  fixtures/opencode/invalid-approve-workflow-change.json \
  "should reject approve when workflow files changed"

run_validator_expected_fail \
  "approve + sensitive file" \
  fixtures/opencode/invalid-approve-sensitive-file.json \
  "should reject approve when sensitive files changed"

run_validator_expected_fail \
  "approve + confidence=low" \
  fixtures/opencode/invalid-approve-low-confidence.json \
  "should reject approve with low confidence"

run_validator_expected_fail \
  "approve + stack drift" \
  fixtures/opencode/invalid-approve-stack-drift.json \
  "should reject approve for stack drift"

# --- Summary ------------------------------------------------------------------

TOTAL=$((PASSED + FAILED))
echo
echo "Results: $PASSED/$TOTAL passed, $FAILED failed"

if [[ $FAILED -eq 0 ]]; then
  echo "All tests passed."
  exit 0
else
  echo "Some tests failed."
  exit 1
fi
