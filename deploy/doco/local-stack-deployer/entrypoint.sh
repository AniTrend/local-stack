#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

LOCK_FILE="/tmp/local-stack-deploy.lock"
REPO="${LOCAL_STACK_REPOSITORY:?LOCAL_STACK_REPOSITORY is required}"
REF="${LOCAL_STACK_REF:-dev}"
WORKDIR="${LOCAL_STACK_WORKDIR:-/workspace/local-stack}"
MODE="${LOCAL_STACK_DEPLOY_MODE:-secrets}"
STACKS="${LOCAL_STACK_TARGET_STACKS:-infrastructure,observability,platform}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another local-stack deployment is already running; exiting."
  exit 75
fi

# Use fetch + reset pattern on persistent workspace volume
if [[ ! -d "$WORKDIR/.git" ]]; then
  echo "Cloning repository into $WORKDIR..."
  git clone --branch "$REF" --depth 10 "$REPO" "$WORKDIR"
fi

cd "$WORKDIR"

echo "Fetching latest from origin/$REF..."
git fetch --prune origin "$REF"
git reset --hard "origin/$REF"

echo "Setting up Python environment..."
rm -rf tools/.venv
python3 -m venv tools/.venv
tools/.venv/bin/python -m pip install --upgrade pip
tools/.venv/bin/python -m pip install -r tools/requirements.txt

echo "Running pre-deployment checks..."
./stackctl.sh doctor --fix-network
./stackctl.sh sync

case "$MODE" in
  secrets)
    echo "Deploying with SOPS secrets mode..."
    ./stackctl.sh secrets deploy
    ;;
  plain-env)
    echo "Deploying with plain env mode..."
    ./stackctl.sh up --no-logs -s "$STACKS"
    ;;
  dry-run)
    echo "Running dry-run deployment..."
    ./stackctl.sh up --dry-run --no-logs -s "$STACKS"
    ;;
  *)
    echo "Unknown LOCAL_STACK_DEPLOY_MODE: $MODE" >&2
    exit 2
    ;;
esac

echo "Deployment complete. Checking service status..."
./stackctl.sh status
