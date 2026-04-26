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
	generate	(Re-)generate stacks/ from compose file sources
	sync		Check if stacks/ matches compose sources; exits 1 on drift
	help		Show this help message and exit

Examples:
	$SCRIPT_NAME up --no-logs -s infrastructure,observability
	$SCRIPT_NAME down -y --remove-network -s platform
	$SCRIPT_NAME status -s infrastructure
	$SCRIPT_NAME logs infrastructure_traefik observability_prometheus
	$SCRIPT_NAME generate
	$SCRIPT_NAME sync

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

# Render a pre-merged stack file (stacks/*.yml) through tools/render_compose.py.
# This performs per-service ${VAR} substitution using each service's env_file(s)
# and writes the result to .rendered/ (which is git-ignored).
# The rendered file — never the source stack file — is what docker stack deploy reads.
render_stack_file() {
	local in_file="$1"
	local stack_name
	stack_name="$(basename "${in_file%.yml}")"
	stack_name="${stack_name%.yaml}"
	local out_dir="${RENDER_DIR:-$SCRIPT_DIR/.rendered}"
	mkdir -p "$out_dir"
	local out_file="$out_dir/${stack_name}.rendered.yml"

	if command -v python3 >/dev/null 2>&1; then
		if python3 "$SCRIPT_DIR/tools/render_compose.py" \
				-i "$in_file" \
				-o "$out_file" \
				--repo-root "$SCRIPT_DIR" >/dev/null 2>&1; then
			printf '%s\n' "$out_file"
			return 0
		else
			log "Warning: render failed for $in_file; deploying unrendered (labels with \${VAR} may not resolve)"
		fi
	else
		log "Warning: python3 not found; skipping render for $in_file (labels with \${VAR} may not resolve)"
	fi
	printf '%s\n' "$in_file"
}

# Prefer docker compose plugin, fall back to docker-compose if available
# Always pass --project-directory so relative paths (env_file, bind mounts) in
# stacks/*.yml resolve against the repo root, not the stack file's directory.
compose_config() {
	local file="$1"
	if docker compose version >/dev/null 2>&1; then
		docker compose --project-directory "$SCRIPT_DIR" -f "$file" config
	elif command -v docker-compose >/dev/null 2>&1; then
		docker-compose --project-directory "$SCRIPT_DIR" -f "$file" config
	else
		err "Neither 'docker compose' nor 'docker-compose' is available to validate $file"
		return 1
	fi
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

cmd_generate() {
	local DRY_RUN=false
	local STACKS_ARG=""

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			--dry-run)
				DRY_RUN=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				STACKS_ARG="${2:-}"; shift 2 ;;
			-h|--help)
				log "Generate stacks/ from compose sources. Options: --dry-run, -s/--stacks <list>"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for generate: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	if ! command -v python3 >/dev/null 2>&1; then
		err "python3 is required for 'generate'"
		exit 2
	fi

	local gen_args=()
	[[ "$DRY_RUN" = true ]] && gen_args+=(--dry-run)
	[[ -n "$STACKS_ARG" ]] && gen_args+=(-s "$STACKS_ARG")

	log "Generating stack files from compose sources..."
	python3 "$SCRIPT_DIR/tools/generate_stacks.py" ${gen_args[@]+"${gen_args[@]}"}
}

cmd_sync() {
	local QUIET=false

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-q|--quiet)
				QUIET=true; shift ;;
			-h|--help)
				log "Check if stacks/ is in sync with compose sources. Exits 1 on drift."; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for sync: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	if ! command -v python3 >/dev/null 2>&1; then
		err "python3 is required for 'sync'"
		exit 2
	fi

	local tmp_dir
	tmp_dir="$(mktemp -d)"
	trap "rm -rf '$tmp_dir'" EXIT

	[[ "$QUIET" = false ]] && log "Checking stack drift (generating to temp dir)..."
	python3 "$SCRIPT_DIR/tools/generate_stacks.py" --output-dir "$tmp_dir" 2>/dev/null || true

	local drift=false
	for stack in "${STACK_FILES[@]}"; do
		local generated="$tmp_dir/${stack}.yml"
		local current="$STACKS_DIR/${stack}.yml"
		if [[ ! -f "$generated" ]]; then
			log "Warning: generator produced no output for: $stack"
			continue
		fi
		if [[ ! -f "$current" ]]; then
			log "DRIFT: $current does not exist (not yet generated)"
			drift=true
			continue
		fi
		if ! diff -q "$generated" "$current" >/dev/null 2>&1; then
			drift=true
			if [[ "$QUIET" = false ]]; then
				log "DRIFT detected in: $stack"
				diff "$current" "$generated" || true
			else
				log "DRIFT: $stack"
			fi
		else
			[[ "$QUIET" = false ]] && log "OK: $stack is in sync"
		fi
	done

	rm -rf "$tmp_dir"
	trap - EXIT

	if [[ "$drift" = true ]]; then
		[[ "$QUIET" = false ]] && log "Drift detected. Run: $SCRIPT_NAME generate"
		exit 1
	fi
	[[ "$QUIET" = false ]] && log "All stacks are in sync with compose sources."
}

cmd_up() {
	local FOLLOW_LOGS=true
	local DRY_RUN=false
	local SKIP_GENERATE=false
	TARGET_STACKS=("${STACK_FILES[@]}")

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-n|--no-logs)
				FOLLOW_LOGS=false; shift ;;
			--dry-run)
				DRY_RUN=true; shift ;;
			--skip-generate)
				SKIP_GENERATE=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "Deploy stacks and optionally follow logs. Options: -n/--no-logs, --dry-run, --skip-generate, -s/--stacks <list> (comma-separated: ${STACK_FILES[*]})"; exit 0 ;;
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

	# Auto-regenerate stacks when any compose/fragment source is newer than the oldest stack file
	if [[ "$SKIP_GENERATE" = false ]] && command -v python3 >/dev/null 2>&1; then
		local _oldest=9999999999 _needs_regen=false _mt
		for _s in "${TARGET_STACKS[@]}"; do
			if [[ ! -f "$STACKS_DIR/${_s}.yml" ]]; then
				_needs_regen=true; break
			fi
			_mt="$(stat -f '%m' "$STACKS_DIR/${_s}.yml" 2>/dev/null || stat -c '%Y' "$STACKS_DIR/${_s}.yml" 2>/dev/null || echo 0)"
			[[ "$_mt" -lt "$_oldest" ]] && _oldest="$_mt"
		done
		if [[ "$_needs_regen" = false ]]; then
			while IFS= read -r _src; do
				[[ -z "$_src" ]] && continue
				_mt="$(stat -f '%m' "$_src" 2>/dev/null || stat -c '%Y' "$_src" 2>/dev/null || echo 0)"
				if [[ "$_mt" -gt "$_oldest" ]]; then _needs_regen=true; break; fi
			done < <(find "$SCRIPT_DIR" -type f \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'swarm.fragment.yml' \) 2>/dev/null || true)
		fi
		if [[ "$_needs_regen" = true ]]; then
			log "Source files are newer than stacks/ — auto-regenerating..."
			if [[ "$DRY_RUN" = true ]]; then
				log "DRY-RUN: would run: python3 $SCRIPT_DIR/tools/generate_stacks.py"
			else
				python3 "$SCRIPT_DIR/tools/generate_stacks.py"
			fi
		fi
	fi

	for stack in "${TARGET_STACKS[@]}"; do
		local file
		if ! file="$(find_stack_file "$stack")"; then
			err "Stack file not found for '$stack' in stacks/ or repo root (.yml/.yaml) -- skipping"
			continue
		fi
		# Render stacks/*.yml → .rendered/*.rendered.yml before deploying.
		# The render step substitutes ${VAR} in labels/commands/healthchecks using
		# each service's env_file(s). The rendered file is git-ignored; the source
		# stack file (with placeholders) is what gets committed.
		local render_file
		render_file="$(render_stack_file "$file")"
		if [[ "$DRY_RUN" = true ]]; then
			log "DRY-RUN: would run: docker stack deploy -c $render_file $stack"
			log "DRY-RUN: validating rendered file: $render_file"
			compose_config "$render_file" >/dev/null || true
		else
			log "Deploying stack: $stack (rendered: $render_file)"
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
	local FIX_VOLUMES=false
	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			--fix-network)
				FIX_NETWORK=true; shift ;;
			--fix-volumes)
				FIX_VOLUMES=true; shift ;;
			-h|--help)
				log "Run preflight checks. Options: --fix-network (create traefik-public if missing), --fix-volumes (create missing external named volumes)"; exit 0 ;;
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
			# Render stacks/*.yml → .rendered/ so compose_config sees fully-resolved vars
			local render_file
			render_file="$(render_stack_file "$file_path")"
			local validated=false
			if compose_config "$render_file" >/dev/null 2>&1; then
				log "OK: '$stack' compose syntax valid (rendered: $render_file)"
				validated=true
			else
				err "Validation failed for '$stack' (rendered: $render_file)"
			fi

			# Optionally ensure external named volumes exist
			if [[ "$FIX_VOLUMES" = true ]]; then
				# Extract external named volumes from the rendered file (best-effort awk/yq-less parsing)
				# Look for pattern under top-level volumes: name: <name> and external: true
				# This is a heuristic and may miss exotic YAML, but works for our stacks.
				local vol_names
				vol_names=$(awk '
				  /^volumes:/ {invol=1; next}
				  invol==1 && /^[^[:space:]]/ {invol=0}
				  invol==1 {
				    if ($0 ~ /^[[:space:]]{2,}[A-Za-z0-9_-]+:$/) {
				      if (keyname != "" && ext == 1) {
				        if (volname != "") print volname; else print keyname;
				      }
				      keyname=$1; sub(":", "", keyname); volname=""; ext=0;
				    } else if ($1 == "name:") {
				      volname=$2;
				    } else if ($1 == "external:" && $2 ~ /true/) {
				      ext=1;
				    }
				  }
				  END { if (keyname != "" && ext == 1) { if (volname != "") print volname; else print keyname; } }
				' "$render_file") || true
				if [[ -n "$vol_names" ]]; then
					while IFS= read -r vol; do
						[[ -z "$vol" ]] && continue
						if docker volume ls --format '{{.Name}}' | grep -qx "$vol"; then
							log "OK: external volume exists: $vol"
						else
							log "Creating missing external volume: $vol"
							docker volume create "$vol" >/dev/null 2>&1 || log "Warning: failed to create volume $vol"
						fi
					done <<< "$vol_names"
				fi
			fi
			# Re-validate after creating volumes if initial validation failed
			if [[ "$FIX_VOLUMES" = true && "$validated" = false ]]; then
				if compose_config "$render_file" >/dev/null 2>&1; then
					log "OK: '$stack' compose syntax valid after fixing volumes (rendered: $render_file)"
					validated=true
				fi
			fi
			if [[ "$validated" = false ]]; then
				overall_ok=false
			fi
		else
			err "Missing stack file for '$stack' (looked in stacks/ and repo root)"
			overall_ok=false
		fi
	done

	# x-stack annotation check
	log "Checking x-stack annotations in compose files..."
	local missing_xstack=0
	while IFS= read -r _cf; do
		[[ -z "$_cf" ]] && continue
		if ! grep -q '^x-stack:' "$_cf" 2>/dev/null; then
			log "NOTE: missing x-stack: in $_cf"
			missing_xstack=$((missing_xstack+1))
		fi
	done < <(find "$SCRIPT_DIR" -mindepth 2 -maxdepth 4 -type f \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' \) 2>/dev/null || true)
	if [[ "$missing_xstack" -eq 0 ]]; then
		log "OK: all compose files have x-stack annotations"
	else
		log "NOTE: $missing_xstack compose file(s) missing x-stack annotation"
	fi

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
	up|down|status|logs|doctor|env|generate|sync|help|-h|--help)
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
	generate)
		cmd_generate "$@" ;;
	sync)
		cmd_sync "$@" ;;
	doctor)
		cmd_doctor "$@" ;;
	help|-h|--help)
		print_usage ;;
	*)
		err "Unknown command: $SUBCOMMAND"; print_usage; exit 2 ;;
esac

exit 0
