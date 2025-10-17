#!/usr/bin/env bash

# Compatibility wrapper for the Python CLI (tools/stackctl_cli.py)
# Keeps existing entrypoint while delegating to the new implementation.

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
PY_CLI="$SCRIPT_DIR/tools/stackctl_cli.py"

info() { printf "[info] %s\n" "$*"; }
warn() { printf "[warn] %s\n" "$*"; }
die() { printf "[error] %s\n" "$*" >&2; exit 1; }

run_py() {
  # run the Python CLI with forwarded args
  python3 "$PY_CLI" "$@"
}

check_py_cli() {
  if [[ ! -f "$PY_CLI" ]]; then
    die "Python CLI not found at $PY_CLI"
  fi
}

bootstrap() {
  info "Copying .env.example files..."
  # Create missing .env files from examples
  find . -type f -name '.env.example' -print0 | while IFS= read -r -d '' src; do
    dst="${src%.env.example}.env"
    if [ ! -e "$dst" ]; then
      info "create $dst"
      cp "$src" "$dst"
    fi
  done

  if [ -f tools/requirements.txt ]; then
    if [ -n "${VIRTUAL_ENV:-}" ]; then
      info "Installing Python requirements..."
      pip install -r tools/requirements.txt
    else
      warn "No Python venv active. Activate your venv before running bootstrap for Python deps."
    fi
  fi

  if command -v docker >/dev/null 2>&1; then
    info "Docker version: $(docker --version)"
    if docker info | grep -q 'Swarm: active'; then
      info "Docker Swarm is active."
    else
      warn "Docker Swarm is not active. Run: docker swarm init"
    fi
  else
    die "Docker not found. Please install Docker Desktop or Docker Engine."
  fi

  printf "\n[bootstrap] Next steps:\n"
  printf "  - Review .env files and adjust as needed.\n"
  printf "  - Run ./stackctl.sh doctor --fix-network\n"
  printf "  - Run ./stackctl.sh up\n"
  printf "  - See tools/README.md for CLI usage.\n"
}

check_py_cli

cmd="${1:-}"
shift || true

case "${cmd:-}" in
  up|deploy )
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
    exec run_py deploy "${args[@]:-}" ;;

  down)
    exec run_py down "$@" ;;

  status)
    exec run_py status "$@" ;;

  logs)
    exec run_py logs "$@" ;;

  env)
    exec run_py env "$@" ;;

  doctor)
    exec run_py doctor run "$@" ;;

  --bootstrap|bootstrap)
    bootstrap
    exit 0 ;;

  help|-h|--help)
    exec run_py --help ;;

  "" )
    # No command supplied: show help (do not default to deploy)
    exec run_py --help ;;

  *)
    printf 'ERROR: unknown command "%s"\n\n' "${cmd:-}" >&2
    exec run_py --help ;;
esac


