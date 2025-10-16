#!/usr/bin/env bash

# Compatibility wrapper for the Python CLI (tools/stackctl_cli.py)
# Keeps existing entrypoint while delegating to the new implementation.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY_CLI="$SCRIPT_DIR/tools/stackctl_cli.py"

if [[ ! -f "$PY_CLI" ]]; then
  printf 'ERROR: Python CLI not found at %s\n' "$PY_CLI" >&2
  exit 2
fi

cmd="${1:-}"
shift || true

case "${cmd:-}" in
  up|deploy|"" )
    # Map legacy flags: --no-logs -> --no-follow-logs
    args=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        -n|--no-logs)
          args+=("--no-follow-logs"); shift ;;
        --dry-run|-s|--stacks|--env)
          # pass-through + value when applicable
          if [[ "$1" == "-s" || "$1" == "--stacks" || "$1" == "--env" ]]; then
            args+=("$1" "${2:-}"); shift 2 || true
          else
            args+=("$1"); shift
          fi ;;
        *) args+=("$1"); shift ;;
      esac
    done
    exec python3 "$PY_CLI" deploy "${args[@]:-}" ;;

  down)
    exec python3 "$PY_CLI" down "$@" ;;

  status)
    exec python3 "$PY_CLI" status "$@" ;;

  logs)
    exec python3 "$PY_CLI" logs "$@" ;;

  env)
    exec python3 "$PY_CLI" env "$@" ;;

  doctor)
    exec python3 "$PY_CLI" doctor run "$@" ;;

  help|-h|--help)
    exec python3 "$PY_CLI" --help ;;

  *)
    # default to deploy
    set +e
    printf 'Unknown or missing command "%s" — delegating to deploy.\n' "${cmd:-}" >&2
    set -e
    exec python3 "$PY_CLI" deploy "$@" ;;
esac

