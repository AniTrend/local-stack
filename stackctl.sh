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
	env		List or recreate .env files from .env.example (safe-guarded)
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
# Swarm stack definitions live under stacks/ (preferred); root-level docker-compose.* files are legacy fallbacks
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

# Render a compose file with per-service env interpolation using tools/render_compose.py
render_compose_file() {
	local in_file="$1"
	local out_dir out_file base base_no_ext
	# Allow override via RENDER_DIR, default to repo-local hidden folder
	out_dir="${RENDER_DIR:-$SCRIPT_DIR/.rendered}"
	mkdir -p "$out_dir"
	base="$(basename "$in_file")"
	base_no_ext="${base%.yml}"
	base_no_ext="${base_no_ext%.yaml}"

	# Keep rendered filenames prefixed with docker-compose.* for consistency
	local out_base
	case "$base" in
		docker-compose.*.yml|docker-compose.*.yaml)
			out_base="$base_no_ext" # already prefixed
			;;
		*.yml|*.yaml)
			# If coming from stacks/<name>.yml, prefix with docker-compose.
			local name_no_ext="$base_no_ext"
			out_base="docker-compose.${name_no_ext}"
			;;
		*)
			out_base="$base_no_ext"
			;;
	esac
	out_file="$out_dir/${out_base}.rendered.yml"

	if command -v python3 >/dev/null 2>&1; then
		if python3 "$SCRIPT_DIR/tools/render_compose.py" -i "$in_file" -o "$out_file" --repo-root "$SCRIPT_DIR" >/dev/null 2>&1; then
			printf '%s\n' "$out_file"
			return 0
		else
			log "Warning: compose render failed for $in_file; using original file"
		fi
	else
		log "Warning: python3 not found; skipping compose render for $in_file"
	fi
	printf '%s\n' "$in_file"
}

# Find a stack file by name with common fallbacks (.yml/.yaml in repo root)
find_stack_file() {
	local name="$1"
	local candidates=(
		"$SCRIPT_DIR/stacks/${name}.yml"
		"$SCRIPT_DIR/stacks/${name}.yaml"
		"$SCRIPT_DIR/docker-compose.${name}.yml"
		"$SCRIPT_DIR/docker-compose.${name}.yaml"
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

# Parse a comma-separated stacks list and validate
set_target_stacks() {
	local arg="${1:-}"
	local tokens=()
	local IFS=','
	read -r -a tokens <<< "$arg"
	local parsed=()
	for t in "${tokens[@]}"; do
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

# Discover directories containing a .env.example (portable across macOS/Linux)
discover_env_example_dirs() {
	local found=()
	while IFS= read -r path; do
		[[ -z "$path" ]] && continue
		local dir
		dir="$(dirname "$path")"
		found+=("$dir")
	done < <( (find "$SCRIPT_DIR" -type f -name '.env.example' 2>/dev/null) || true )

	if [[ ${#found[@]} -gt 0 ]]; then
		printf '%s\n' "${found[@]}" | awk '!x[$0]++' | sort
	fi
}

# Parse comma-separated user-provided paths and normalize to absolute directories
parse_env_paths() {
	local input="$1"
	local IFS=','
	read -r -a toks <<< "$input"
	local out=()
	for p in "${toks[@]}"; do
		p="${p//[[:space:]]/}"
		[[ -z "$p" ]] && continue
		local abs
		if [[ -d "$SCRIPT_DIR/$p" ]]; then
			abs="$(cd "$SCRIPT_DIR/$p" && pwd)"
		elif [[ -f "$SCRIPT_DIR/$p" ]]; then
			abs="$(cd "$(dirname "$SCRIPT_DIR/$p")" && pwd)"
		else
			if [[ -d "$p" ]]; then
				abs="$(cd "$p" && pwd)"
			elif [[ -f "$p" ]]; then
				abs="$(cd "$(dirname "$p")" && pwd)"
			else
				err "Path not found: $p"
				continue
			fi
		fi
		out+=("$abs")
	done
	if [[ ${#out[@]} -gt 0 ]]; then
		printf '%s\n' "${out[@]}" | awk '!x[$0]++'
	fi
}

backup_file() {
	local file="$1"
	local ts
	ts="$(date +%Y%m%d%H%M%S)"
	local backup="${file}.bak.${ts}"
	cp -p "$file" "$backup"
	printf '%s' "$backup"
}

cmd_env() {
	local DO_LIST=false
	local DO_RECREATE=false
	local FORCE=false
	local ASSUME_YES=false
	local DRY_RUN=false
	local PATHS=""

	# Summary accumulators
	local total=0
	local have_env=0
	local missing_env=0
	local skipped_no_example=0
	local created_count=0
	local overwritten_count=0
	local skipped_exists_count=0
	local missing_example_count=0
	local -a missing_env_list=()
	local -a skipped_list=()
	local -a created_list=()
	local -a overwritten_list=()
	local -a backup_list=()
	local -a skipped_exists_list=()
	local -a missing_example_list=()

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			--list)
				DO_LIST=true; shift ;;
			--recreate)
				DO_RECREATE=true; shift ;;
			--paths)
				[[ $# -lt 2 ]] && { err "--paths requires a comma-separated list of dirs/files"; exit 2; }
				PATHS="${2:-}"; shift 2 ;;
			-f|--force)
				FORCE=true; shift ;;
			-y|--yes)
				ASSUME_YES=true; shift ;;
			--dry-run)
				DRY_RUN=true; shift ;;
			-h|--help)
				log "Manage .env files from .env.example. Options: --list, --recreate, --paths <dirs>, -f/--force, -y/--yes, --dry-run"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for env: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	if [[ "$DO_LIST" = false && "$DO_RECREATE" = false ]]; then
		DO_LIST=true
	fi

	local targets=()
	if [[ -n "$PATHS" ]]; then
		while IFS= read -r dir; do
			[[ -z "$dir" ]] || targets+=("$dir")
		done < <(parse_env_paths "$PATHS")
	else
		while IFS= read -r dir; do
			[[ -z "$dir" ]] || targets+=("$dir")
		done < <(discover_env_example_dirs)
	fi

	if [[ ${#targets[@]} -eq 0 ]]; then
		log "No .env.example locations discovered."
		exit 0
	fi

	if [[ "$DO_LIST" = true ]]; then
		log "Discovered env locations (status shows if .env exists):"
		for dir in "${targets[@]}"; do
			if [[ -f "$dir/.env.example" ]]; then
				if [[ -f "$dir/.env" ]]; then
					printf '[OK]       %s (has .env)\n' "$dir"
					have_env=$((have_env+1))
				else
					printf '[MISSING]  %s (no .env)\n' "$dir"
					missing_env=$((missing_env+1))
					missing_env_list+=("$dir")
				fi
			else
				printf '[SKIP]     %s (no .env.example)\n' "$dir"
				skipped_no_example=$((skipped_no_example+1))
				skipped_list+=("$dir")
			fi
		done
		total=${#targets[@]}
		printf '\nSummary: %d discovered | %d with .env | %d missing .env | %d without .env.example\n' "$total" "$have_env" "$missing_env" "$skipped_no_example"
		if [[ $missing_env -gt 0 ]]; then
			printf 'Missing .env in:\n'
			for d in "${missing_env_list[@]}"; do printf '  - %s\n' "$d"; done
		fi
		if [[ $skipped_no_example -gt 0 ]]; then
			printf 'No .env.example in:\n'
			for d in "${skipped_list[@]}"; do printf '  - %s\n' "$d"; done
		fi
	fi

	if [[ "$DO_RECREATE" = true ]]; then
		log "Recreating .env from .env.example for ${#targets[@]} location(s)"
		for dir in "${targets[@]}"; do
			local ex="$dir/.env.example"
			local env="$dir/.env"
			if [[ ! -f "$ex" ]]; then
				log "Skipping: no .env.example in $dir"
				missing_example_count=$((missing_example_count+1))
				missing_example_list+=("$dir")
				continue
			fi
			if [[ -f "$env" && "$FORCE" = false ]]; then
				log "Skipping (exists): $env (use --force to overwrite)"
				skipped_exists_count=$((skipped_exists_count+1))
				skipped_exists_list+=("$env")
				continue
			fi

			if [[ -f "$env" && "$FORCE" = true ]]; then
				if [[ "$ASSUME_YES" = false ]]; then
					printf 'About to overwrite %s. Create backup and continue? [y/N]: ' "$env"
					read -r ans
					case "$ans" in
						[Yy]|[Yy][Ee][Ss]) ;;
						*) log "Aborting overwrite for $env"; continue ;;
					esac
				fi
				if [[ "$DRY_RUN" = true ]]; then
					log "DRY-RUN: backup and overwrite $env from $ex"
					overwritten_count=$((overwritten_count+1))
					overwritten_list+=("$env (dry-run)")
				else
					local backup
					backup="$(backup_file "$env")"
					log "Backed up $env -> $backup"
					cp -f "$ex" "$env"
					overwritten_count=$((overwritten_count+1))
					overwritten_list+=("$env")
					backup_list+=("$backup")
				fi
			else
				if [[ "$DRY_RUN" = true ]]; then
					log "DRY-RUN: create $env from $ex"
					created_count=$((created_count+1))
					created_list+=("$env (dry-run)")
				else
					cp -f "$ex" "$env"
					created_count=$((created_count+1))
					created_list+=("$env")
				fi
			fi
		done
		# Recreate summary
		printf '\nSummary: %d targets | %d created | %d overwritten | %d skipped (exists) | %d missing .env.example\n' \
			"${#targets[@]}" "$created_count" "$overwritten_count" "$skipped_exists_count" "$missing_example_count"
		if [[ $created_count -gt 0 ]]; then
			printf 'Created .env files:\n'; for f in "${created_list[@]}"; do printf '  - %s\n' "$f"; done
		fi
		if [[ $overwritten_count -gt 0 ]]; then
			printf 'Overwritten .env files:\n'; for f in "${overwritten_list[@]}"; do printf '  - %s\n' "$f"; done
			# Only show backups when not dry-run
			if [[ ${#backup_list[@]} -gt 0 ]]; then
				printf 'Backups created:\n'; for b in "${backup_list[@]}"; do printf '  - %s\n' "$b"; done
			fi
		fi
		if [[ $skipped_exists_count -gt 0 ]]; then
			printf 'Skipped (existing .env, use --force to overwrite):\n'; for f in "${skipped_exists_list[@]}"; do printf '  - %s\n' "$f"; done
		fi
		if [[ $missing_example_count -gt 0 ]]; then
			printf 'Missing .env.example in:\n'; for d in "${missing_example_list[@]}"; do printf '  - %s\n' "$d"; done
		fi
	fi
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
			err "Stack file not found for '$stack' in stacks/ or repo root (.yml/.yaml) -- skipping"
			continue
		fi
		# Render into a temporary sibling file to resolve service-level env vars in labels/commands/etc.
		local render_file
		render_file="$(render_compose_file "$file")"
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: would run: docker stack deploy -c $render_file $stack"
			log "DRY-RUN: validating compose file: $render_file"
			compose_config "$render_file" || true
		else
			log "Deploying stack: $stack (file: $render_file)"
			docker stack deploy -c "$render_file" "$stack"
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
			# Attempt to render first for accurate validation
			local rendered
			rendered="$(render_compose_file "$file_path")"
			if compose_config "$rendered" >/dev/null 2>&1; then
				log "OK: '$stack' compose syntax valid (validated: $rendered)"
			else
				err "Validation failed for '$stack' ($rendered)"
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
	up|down|status|logs|doctor|env|help|-h|--help)
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
	env)
		cmd_env "$@" ;;
	doctor)
		cmd_doctor "$@" ;;
	help|-h|--help)
		print_usage ;;
	*)
		err "Unknown command: $SUBCOMMAND"; print_usage; exit 2 ;;
esac

exit 0
