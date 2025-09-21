#!/usr/bin/env bash

# Safe/strict shell settings
set -euo pipefail
IFS=$'\n\t'

SCRIPT_NAME="$(basename "$0")"

print_usage() {
	cat <<USAGE
Usage: $SCRIPT_NAME <command> [options]

Manage the Docker Swarm stacks for this repo.

Commands:
	up		Deploy the stacks (default if no command is provided)
	down		Remove the stacks
	status		List services for each stack
	logs		Follow logs for key services or specified services
	doctor		Run preflight checks and optional fixes
	help		Show this help message and exit

Examples:
	$SCRIPT_NAME up --no-logs -s infrastructure,observability
	$SCRIPT_NAME down -y --remove-network -s platform
	$SCRIPT_NAME status -s infrastructure
	$SCRIPT_NAME logs infrastructure_traefik observability_prometheus

Common options:
	-h, --help	Show help (also works per-command)
USAGE
}

# Helpers
log() { printf '%s\n' "$*" >&2; }
err() { log "ERROR: $*"; }

# Determine repository root (directory containing this script)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
STACKS_DIR="$SCRIPT_DIR/stacks"

check_command() {
	command -v "$1" >/dev/null 2>&1 || { err "'$1' is required but not installed or not on PATH"; exit 2; }
}

# Prefer docker compose plugin, fall back to docker-compose if available
compose_config() {
	local file="$1"
	if docker compose version >/dev/null 2>&1; then
		docker compose -f "$file" config
	elif command -v docker-compose >/dev/null 2>&1; then
		docker-compose -f "$file" config
	else
		err "Neither 'docker compose' nor 'docker-compose' is available to validate $file"
		return 1
	fi
}

# Find a stack file by name with common fallbacks (stacks/ and repo root, .yml/.yaml)
find_stack_file() {
	local name="$1"
	local candidates=(
		"$STACKS_DIR/${name}.yml"
		"$STACKS_DIR/${name}.yaml"
		"$SCRIPT_DIR/${name}.yml"
		"$SCRIPT_DIR/${name}.yaml"
	)
	for f in "${candidates[@]}"; do
		if [[ -f "$f" ]]; then
			printf '%s\n' "$f"
			return 0
		fi
	done
	return 1
}

ensure_swarm_info() {
	SWARM_STATE="$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || true)"
	if [[ "$SWARM_STATE" != "active" ]]; then
		log "Docker Swarm does not appear to be active on this host (Swarm state: ${SWARM_STATE:-unknown})."
		log "If you intend to deploy stacks to a Swarm, run: docker swarm init"
	fi
}

ensure_traefik_network() {
	local dry_run=${1:-false}
	if docker network ls --format '{{.Name}}' | grep -qx "traefik-public"; then
		log "Found existing 'traefik-public' network."
	else
		if [[ "${SWARM_STATE:-}" = "active" ]]; then
			log "Creating 'traefik-public' overlay network (attachable)"
			if [[ "$dry_run" = false ]]; then
				docker network create --driver=overlay --attachable traefik-public || log "Warning: failed to create traefik-public network (may already exist)."
			else
				log "DRY-RUN: would create 'traefik-public' network"
			fi
		else
			log "Skipping network creation because Swarm is not active."
		fi
	fi
}

STACK_FILES=(infrastructure observability platform)
DEFAULT_LOG_SERVICES=(observability_prometheus observability_loki infrastructure_traefik)

# Selected stacks (defaults to all unless overridden via -s/--stacks)
TARGET_STACKS=()

set_target_stacks() {
	local arg="${1:-}"
	local tokens=()
	local IFS=','
	read -r -a tokens <<< "$arg"
	local parsed=()
	for t in "${tokens[@]}"; do
		# trim whitespace
		t="${t//[[:space:]]/}"
		[[ -z "$t" ]] && continue
		local valid=false
		for a in "${STACK_FILES[@]}"; do
			if [[ "$t" == "$a" ]]; then
				valid=true
				break
			fi
		done
		if [[ "$valid" == false ]]; then
			err "Unknown stack '$t'. Allowed: ${STACK_FILES[*]}"
			exit 2
		fi
		parsed+=("$t")
	done
	if [[ ${#parsed[@]} -eq 0 ]]; then
		err "No valid stacks specified with --stacks"
		exit 2
	fi
	TARGET_STACKS=("${parsed[@]}")
}

cmd_up() {
	local FOLLOW_LOGS=true
	local DRY_RUN=false
	TARGET_STACKS=("${STACK_FILES[@]}")

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-n|--no-logs)
				FOLLOW_LOGS=false; shift ;;
			--dry-run)
				DRY_RUN=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "Deploy stacks and optionally follow logs. Options: -n/--no-logs, --dry-run, -s/--stacks <list> (comma-separated: ${STACK_FILES[*]})"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for up: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	check_command docker
	ensure_swarm_info
	ensure_traefik_network "$DRY_RUN"

	for stack in "${TARGET_STACKS[@]}"; do
		local file
		if ! file="$(find_stack_file "$stack")"; then
			err "Stack file not found for '$stack' in $STACKS_DIR or repo root (.yml/.yaml) -- skipping"
			continue
		fi
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: would run: docker stack deploy -c $file $stack"
			log "DRY-RUN: validating compose file: $file"
			compose_config "$file" || true
		else
			log "Deploying stack: $stack (file: $file)"
			docker stack deploy -c "$file" "$stack"
		fi
	done

	for stack in "${TARGET_STACKS[@]}"; do
		log "Services for stack: $stack"
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: docker stack services $stack"
		else
			docker stack services "$stack" || log "Warning: failed to list services for $stack"
		fi
	done

	# Follow logs if requested
	if [[ "$FOLLOW_LOGS" = true && "$DRY_RUN" = false ]]; then
		cmd_logs "${DEFAULT_LOG_SERVICES[@]}"
	else
		log "Not following logs (FOLLOW_LOGS=$FOLLOW_LOGS, DRY_RUN=$DRY_RUN)"
	fi
}

cmd_down() {
	local DRY_RUN=false
	local REMOVE_NETWORK=false
	local ASSUME_YES=false
	TARGET_STACKS=("${STACK_FILES[@]}")

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			--dry-run)
				DRY_RUN=true; shift ;;
			--remove-network)
				REMOVE_NETWORK=true; shift ;;
			-y|--yes)
				ASSUME_YES=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "Remove stacks. Options: --dry-run, --remove-network, -y/--yes, -s/--stacks <list> (comma-separated: ${STACK_FILES[*]})"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for down: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	check_command docker

	log "Stacks to remove: ${TARGET_STACKS[*]}"
	if [[ "$ASSUME_YES" = false && "$DRY_RUN" = false ]]; then
		printf "Are you sure you want to remove the above stacks? [y/N]: "
		read -r ans
		case "$ans" in
			[Yy]|[Yy][Ee][Ss]) ;;
			*) log "Aborting."; exit 0 ;;
		esac
	fi

	for stack in "${TARGET_STACKS[@]}"; do
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: docker stack rm $stack"
		else
			log "Removing stack: $stack"
			docker stack rm "$stack" || log "Warning: failed to remove stack $stack or it may not exist"
		fi
	done

	if [[ "$REMOVE_NETWORK" = true ]]; then
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: docker network rm traefik-public"
		else
			log "Removing network: traefik-public"
			docker network rm traefik-public || log "Warning: could not remove traefik-public (may not exist or may be in use)"
		fi
	fi
}

cmd_status() {
	check_command docker
	TARGET_STACKS=("${STACK_FILES[@]}")
	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "List services. Options: -s/--stacks <list> (comma-separated: ${STACK_FILES[*]})"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for status: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	for stack in "${TARGET_STACKS[@]}"; do
		log "Services for stack: $stack"
		docker stack services "$stack" || log "Warning: failed to list services for $stack"
	done
}

cmd_logs() {
	check_command docker
	local services=("$@")
	if [[ ${#services[@]} -eq 0 ]]; then
		services=("${DEFAULT_LOG_SERVICES[@]}")
	fi
	local PIDS=()
	cleanup() {
		log "Cleaning up..."
		for pid in "${PIDS[@]:-}"; do
			if kill -0 "$pid" 2>/dev/null; then
				kill "$pid" 2>/dev/null || true
			fi
		done
	}
	trap cleanup EXIT INT TERM

	for svc in "${services[@]}"; do
		log "Following logs for service: $svc"
		docker service logs -f "$svc" 2>&1 | sed "s/^/[$svc] /" &
		PIDS+=("$!")
	done
	wait
}

cmd_doctor() {
	local FIX_NETWORK=false
	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			--fix-network)
				FIX_NETWORK=true; shift ;;
			-h|--help)
				log "Run preflight checks. Options: --fix-network (create traefik-public if missing)"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for doctor: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	# Basic tooling
	check_command docker
	if docker compose version >/dev/null 2>&1; then
		log "Found: docker compose plugin"
	elif command -v docker-compose >/dev/null 2>&1; then
		log "Found: docker-compose (legacy)"
	else
		err "Missing both 'docker compose' and 'docker-compose'"
	fi

	# Swarm state
	ensure_swarm_info

	# Network
	if docker network ls --format '{{.Name}}' | grep -qx "traefik-public"; then
		log "OK: traefik-public network exists"
	else
		if [[ "$FIX_NETWORK" = true ]]; then
			log "Creating missing traefik-public network (overlay, attachable)"
			ensure_traefik_network false
		else
			err "Missing network 'traefik-public' — run: docker network create --driver=overlay --attachable traefik-public"
		fi
	fi

	# Stack files + validation
	local overall_ok=true
	for stack in "${STACK_FILES[@]}"; do
		if file_path="$(find_stack_file "$stack")"; then
			log "OK: found stack file for '$stack': $file_path"
			if compose_config "$file_path" >/dev/null 2>&1; then
				log "OK: '$stack' compose syntax valid"
			else
				err "Validation failed for '$stack' ($file_path)"
				overall_ok=false
			fi
		else
			err "Missing stack file for '$stack' (looked in stacks/ and repo root)"
			overall_ok=false
		fi
	done

	# .env hints for service directories that have docker-compose files
	log "Scanning service folders for .env hints..."
	local service_dirs
	# GNU find on Linux supports -printf; if not available, this block may be skipped
	if service_dirs=$(find "$SCRIPT_DIR" -mindepth 2 -maxdepth 3 -type f \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' \) -printf '%h\n' 2>/dev/null | sort -u); then
		while IFS= read -r dir; do
			[[ -z "$dir" ]] && continue
			if [[ -f "$dir/.env.example" && ! -f "$dir/.env" ]]; then
				log "NOTE: $dir has .env.example but no .env — copy it before deploying"
			fi
		done <<< "$service_dirs"
	else
		log "Skipping .env hint scan (find -printf not supported)"
	fi

	# TLS dev cert hints for Traefik
	local cert_dir="$SCRIPT_DIR/traefik/certs"
	if [[ -d "$cert_dir" ]]; then
		if [[ ! -f "$cert_dir/local-cert.pem" || ! -f "$cert_dir/local-key.pem" ]]; then
			log "NOTE: Traefik dev certs not found in traefik/certs (local-cert.pem/local-key.pem). See stacks/README.md for mkcert instructions."
		else
			log "OK: Traefik dev certs present"
		fi
	fi

	if [[ "$overall_ok" = true ]]; then
		log "Doctor checks completed: no blocking issues detected."
		exit 0
	else
		err "Doctor checks found issues. See messages above."
		exit 1
	fi
}

# Determine subcommand (default: up)
SUBCOMMAND="${1:-}"
case "$SUBCOMMAND" in
	up|down|status|logs|doctor|help|-h|--help)
		[[ $# -gt 0 ]] && shift || true ;;
	*)
		SUBCOMMAND="up" ;;
esac

case "$SUBCOMMAND" in
	up)
		cmd_up "$@" ;;
	down)
		cmd_down "$@" ;;
	status)
		cmd_status "$@" ;;
	logs)
		cmd_logs "$@" ;;
	doctor)
		cmd_doctor "$@" ;;
	help|-h|--help)
		print_usage ;;
	*)
		err "Unknown command: $SUBCOMMAND"; print_usage; exit 2 ;;
esac

exit 0
