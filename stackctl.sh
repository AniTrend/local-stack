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
	secrets		Encrypt, decrypt, deploy, or clean .env.enc files
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

tools_python() {
	local venv_python="$SCRIPT_DIR/tools/.venv/bin/python"
	if [[ -x "$venv_python" ]]; then
		printf '%s\n' "$venv_python"
		return 0
	fi
	if command -v python3 >/dev/null 2>&1; then
		command -v python3
		return 0
	fi
	return 1
}

log_render_setup_hint() {
	log "Render toolchain setup:"
	log "  python3 -m venv tools/.venv"
	log "  tools/.venv/bin/python -m pip install --upgrade pip"
	log "  tools/.venv/bin/python -m pip install -r tools/requirements.txt"
}

# Verify that tools/generate_stacks.py and tools/render_compose.py can run
# (python3 + PyYAML + ruamel.yaml present).
# Exits with a clear error and remediation hint when dependencies are missing.
check_render_deps() {
	local py
	if ! py="$(tools_python)"; then
		err "python3 is required for rendering, and tools/.venv/bin/python was not found."
		log_render_setup_hint
		exit 2
	fi
	if ! "$py" -c "import yaml; import ruamel.yaml" 2>/dev/null; then
		err "PyYAML and ruamel.yaml are required for stack generation/rendering but are not both importable by: $py"
		log_render_setup_hint
		exit 2
	fi
}

file_mtime() {
	local path="$1"
	local mt=""

	# GNU stat on Linux uses -c '%Y'. BSD/macOS stat uses -f '%m'.
	# GNU stat also accepts -f, but with filesystem semantics; validate the
	# result is numeric before using it in arithmetic under set -u.
	if mt="$(stat -c '%Y' "$path" 2>/dev/null)" && [[ "$mt" =~ ^[0-9]+$ ]]; then
		printf '%s\n' "$mt"
		return 0
	fi
	if mt="$(stat -f '%m' "$path" 2>/dev/null)" && [[ "$mt" =~ ^[0-9]+$ ]]; then
		printf '%s\n' "$mt"
		return 0
	fi

	printf '0\n'
}

# Render a pre-merged stack file (stacks/*.yml) through tools/render_compose.py.
# This performs per-service ${VAR} substitution using each service's env_file(s)
# and writes the result to .rendered/ (which is git-ignored).
# The rendered file -- never the source stack file -- is what docker stack deploy reads.
#
# By default, render failure is FATAL because deploying unrendered stacks
# leads to broken ${VAR} placeholders and incorrect env_file path resolution.
# Pass allow_fallback=1 to restore the old warn-and-fallback behaviour
# (only for debugging; never in production).
render_stack_file() {
	local in_file="$1"
	local allow_fallback="${2:-0}"
	local stack_name
	stack_name="$(basename "${in_file%.yml}")"
	stack_name="${stack_name%.yaml}"
	local out_dir="${RENDER_DIR:-$SCRIPT_DIR/.rendered}"
	mkdir -p "$out_dir"
	local out_file="$out_dir/${stack_name}.rendered.yml"
	local py=""

	if py="$(tools_python)"; then
		if "$py" "$SCRIPT_DIR/tools/render_compose.py" \
				-i "$in_file" \
				-o "$out_file" \
				--repo-root "$SCRIPT_DIR" >/dev/null 2>&1; then
			printf '%s\n' "$out_file"
			return 0
		else
			if [[ "$allow_fallback" -eq 1 ]]; then
				log "Warning: render failed for $in_file; deploying unrendered (labels with \${VAR} may not resolve)"
				printf '%s\n' "$in_file"
				return 0
			fi
			err "Render failed for $in_file. Ensure the tools virtualenv is installed and all service env_file paths exist. Re-run with --allow-unrendered only for debugging."
			log_render_setup_hint
			exit 2
		fi
	fi

	if [[ "$allow_fallback" -eq 1 ]]; then
		log "Warning: python3 not found; skipping render for $in_file (labels with \${VAR} may not resolve)"
		printf '%s\n' "$in_file"
		return 0
	fi
	err "python3 not found -- cannot render $in_file. Install python3 and re-run, or use --allow-unrendered only for debugging."
	log_render_setup_hint
	exit 2
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

	local py
	if ! py="$(tools_python)"; then
		err "python3 is required for 'generate', and tools/.venv/bin/python was not found."
		log_render_setup_hint
		exit 2
	fi

	local gen_args=()
	[[ "$DRY_RUN" = true ]] && gen_args+=(--dry-run)
	[[ -n "$STACKS_ARG" ]] && gen_args+=(-s "$STACKS_ARG")

	log "Generating stack files from compose sources..."
	"$py" "$SCRIPT_DIR/tools/generate_stacks.py" ${gen_args[@]+"${gen_args[@]}"}
}

cmd_sync() {
	local QUIET=false
	TARGET_STACKS=("${STACK_FILES[@]}")

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-q|--quiet)
				QUIET=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "Check if stacks/ is in sync with compose sources. Exits 1 on drift. Options: -q/--quiet, -s/--stacks <list>"; exit 0 ;;
			--)
				shift; break ;;
			-*)
				printf '%s: unknown option for sync: %s\n' "$SCRIPT_NAME" "$1" >&2; exit 2 ;;
			*)
				break ;;
		esac
	done

	local py
	if ! py="$(tools_python)"; then
		err "python3 is required for 'sync', and tools/.venv/bin/python was not found."
		log_render_setup_hint
		exit 2
	fi

	local tmp_dir gen_err
	tmp_dir="$(mktemp -d)"
	gen_err="$(mktemp)"
	trap "rm -rf '$tmp_dir' '$gen_err'" EXIT

	[[ "$QUIET" = false ]] && log "Checking stack drift (generating to temp dir)..."
	if ! "$py" "$SCRIPT_DIR/tools/generate_stacks.py" --output-dir "$tmp_dir" 2>"$gen_err"; then
		[[ "$QUIET" = false ]] && cat "$gen_err" >&2
		err "Stack generation failed; cannot verify sync state."
		exit 1
	fi

	local drift=false
	for stack in "${TARGET_STACKS[@]}"; do
		local generated="$tmp_dir/${stack}.yml"
		local current="$STACKS_DIR/${stack}.yml"
		if [[ ! -f "$generated" ]]; then
			log "DRIFT: generator produced no output for $stack"
			drift=true
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

	rm -rf "$tmp_dir" "$gen_err"
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
	local ALLOW_UNRENDERED=false
	TARGET_STACKS=("${STACK_FILES[@]}")

	while [[ $# -gt 0 ]]; do
		case "${1:-}" in
			-n|--no-logs)
				FOLLOW_LOGS=false; shift ;;
			--dry-run)
				DRY_RUN=true; shift ;;
			--skip-generate)
				SKIP_GENERATE=true; shift ;;
			--allow-unrendered)
				ALLOW_UNRENDERED=true; shift ;;
			-s|--stacks)
				[[ $# -lt 2 ]] && { err "--stacks requires a value"; exit 2; }
				set_target_stacks "${2:-}"; shift 2 ;;
			-h|--help)
				log "Deploy stacks and optionally follow logs. Options: -n/--no-logs, --dry-run, --skip-generate, --allow-unrendered, -s/--stacks <list> (comma-separated: ${STACK_FILES[*]})"; exit 0 ;;
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

	# Verify render dependencies before attempting any deployment.
	# Deploying unrendered stacks causes broken ${VAR} placeholders and
	# incorrect env_file path resolution (Docker resolves them relative to
	# the stack file, not the repo root).
	if [[ "$ALLOW_UNRENDERED" = false ]]; then
		check_render_deps
		log "Stack toolchain dependencies OK (PyYAML + ruamel.yaml available)"
	fi

	# Auto-regenerate stacks when any compose/fragment source is newer than the oldest stack file
	local generate_python=""
	if [[ "$SKIP_GENERATE" = false ]] && generate_python="$(tools_python)"; then
		local _oldest=9999999999 _needs_regen=false _mt
		for _s in "${TARGET_STACKS[@]}"; do
			if [[ ! -f "$STACKS_DIR/${_s}.yml" ]]; then
				_needs_regen=true; break
			fi
			_mt="$(file_mtime "$STACKS_DIR/${_s}.yml")"
			[[ "$_mt" -lt "$_oldest" ]] && _oldest="$_mt"
		done
		if [[ "$_needs_regen" = false ]]; then
			while IFS= read -r _src; do
				[[ -z "$_src" ]] && continue
				_mt="$(file_mtime "$_src")"
				if [[ "$_mt" -gt "$_oldest" ]]; then _needs_regen=true; break; fi
			done < <(find "$SCRIPT_DIR" -type f \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'swarm.fragment.yml' \) 2>/dev/null || true)
		fi
		if [[ "$_needs_regen" = true ]]; then
			log "Source files are newer than stacks/ — auto-regenerating..."
			if [[ "$DRY_RUN" = true ]]; then
				log "DRY-RUN: would run: $generate_python $SCRIPT_DIR/tools/generate_stacks.py"
			else
				"$generate_python" "$SCRIPT_DIR/tools/generate_stacks.py"
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
		local fallback=0
		[[ "$ALLOW_UNRENDERED" = true ]] && fallback=1
		render_file="$(render_stack_file "$file" "$fallback")"
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

	# Render toolchain
	local render_python=""
	if render_python="$(tools_python)"; then
		log "Found render Python: $render_python"
		if [[ "$render_python" != "$SCRIPT_DIR/tools/.venv/bin/python" ]]; then
			log "NOTE: tools/.venv/bin/python not found; using global python3 instead."
			log_render_setup_hint
		fi
		if "$render_python" -c "import yaml; import ruamel.yaml" 2>/dev/null; then
			log "OK: stack toolchain (python + PyYAML + ruamel.yaml) available"
		else
			log "NOTE: PyYAML and/or ruamel.yaml missing from render Python: $render_python"
			log_render_setup_hint
		fi
	else
		log "NOTE: python3 not found and tools/.venv/bin/python not found -- stack rendering will not be available"
		log_render_setup_hint
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

cmd_secrets() {
	local OPERATION="${1:-}"
	shift || true

	case "$OPERATION" in
		encrypt|decrypt|deploy|clean)
			;;
		-h|--help)
			log "Manage encrypted .env.enc files with SOPS + age."
			log ""
			log "Usage: $SCRIPT_NAME secrets <operation> [service]"
			log ""
			log "Operations:"
			log "  encrypt [service]  Encrypt .env → .env.enc for one or all services"
			log "  decrypt [service]  Decrypt .env.enc → .env for one or all services"
			log "  deploy   [service] Decrypt, render, deploy, then shred .env"
			log "  clean              Shred all plaintext .env files that have .env.enc"
			log ""
			log "Services are discovered from .env.example files in the repo."
			log "[service] accepts a directory basename (e.g., postgres) or"
			log "a repo-relative path (e.g., apisix/api-gateway)."
			log "If omitted, operates on all discovered services."
			log ""
			log "Requires: sops and age on PATH (for encrypt, decrypt, deploy)."
			exit 0
			;;
		*)
			err "Unknown secrets operation: ${OPERATION:-<none>}"
			log "Usage: $SCRIPT_NAME secrets <encrypt|decrypt|deploy|clean> [service]"
			log "Run: $SCRIPT_NAME secrets --help"
			exit 2
			;;
	esac

	# Discover service directories that have .env.example (reuse existing discovery)
	local -a all_dirs=()
	while IFS= read -r dir; do
		[[ -z "$dir" ]] || all_dirs+=("$dir")
	done < <(discover_env_example_dirs)

	if [[ ${#all_dirs[@]} -eq 0 ]]; then
		log "No service directories found (no .env.example files)."
		exit 0
	fi

	# If a service name is given, filter to that directory
	# Accepts basename (e.g., postgres) or repo-relative path (e.g., apisix/api-gateway)
	local -a target_dirs=()
	if [[ $# -gt 0 ]]; then
		local svc="$1"
		local found=false
		for dir in "${all_dirs[@]}"; do
			local dirname
			dirname="$(basename "$dir")"
			local rel_path="${dir#$SCRIPT_DIR/}"
			if [[ "$dirname" == "$svc" || "$rel_path" == "$svc" ]]; then
				target_dirs=("$dir")
				found=true
				break
			fi
		done
		if [[ "$found" = false ]]; then
			# Build a concise list: show basename, and rel-path when it differs
			local available
			available="$(for d in "${all_dirs[@]}"; do
				local bn="$(basename "$d")"
				local rp="${d#$SCRIPT_DIR/}"
				if [[ "$bn" == "$rp" ]]; then
					printf '%s ' "$bn"
				else
					printf '%s(%s) ' "$bn" "$rp"
				fi
			done)"
			err "Service '$svc' not found. Available: $available"
			exit 2
		fi
	else
		target_dirs=("${all_dirs[@]}")
	fi

	case "$OPERATION" in
		encrypt)
			check_command sops
			check_command age
			_secrets_encrypt "${target_dirs[@]}"
			;;
		decrypt)
			check_command sops
			check_command age
			_secrets_decrypt "${target_dirs[@]}"
			;;
		deploy)
			check_command sops
			check_command age
			_secrets_deploy "${target_dirs[@]}"
			;;
		clean)
			_secrets_clean "${all_dirs[@]}"
			;;
	esac
}

_secrets_encrypt() {
	local -a dirs=("$@")
	local encrypted=0
	local skipped=0

	for dir in "${dirs[@]}"; do
		local env_file="$dir/.env"
		local enc_file="$dir/.env.enc"

		if [[ ! -f "$env_file" ]]; then
			log "SKIP: $dir — no .env file to encrypt"
			skipped=$((skipped+1))
			continue
		fi

		log "Encrypting: $env_file → $enc_file"
		local tmp_enc
		tmp_enc="$(mktemp "${enc_file}.tmp.XXXXXXXXXX")"
		if sops --encrypt --input-type dotenv --output-type dotenv "$env_file" > "$tmp_enc"; then
			mv "$tmp_enc" "$enc_file"
			encrypted=$((encrypted+1))
		else
			err "Failed to encrypt $env_file"
			rm -f "$tmp_enc"
			continue
		fi
	done

	log "Encrypt complete: $encrypted encrypted, $skipped skipped"
}

_secrets_decrypt() {
	local -a dirs=("$@")
	local decrypted=0
	local skipped=0

	for dir in "${dirs[@]}"; do
		local enc_file="$dir/.env.enc"
		local env_file="$dir/.env"

		if [[ ! -f "$enc_file" ]]; then
			log "SKIP: $dir — no .env.enc file to decrypt"
			skipped=$((skipped+1))
			continue
		fi

		log "Decrypting: $enc_file → $env_file"
		local tmp_env
		tmp_env="$(mktemp "${env_file}.tmp.XXXXXXXXXX")"
		local decrypt_ok=false
		# Write to temp file with umask 077, then atomic move into place
		if ( umask 077; sops --decrypt --input-type dotenv --output-type dotenv "$enc_file" > "$tmp_env" ); then
			mv "$tmp_env" "$env_file"
			decrypt_ok=true
		else
			err "Failed to decrypt $enc_file"
			rm -f "$tmp_env"
		fi
		if [[ "$decrypt_ok" = true ]]; then
			decrypted=$((decrypted+1))
		else
			skipped=$((skipped+1))
		fi
	done

	log "Decrypt complete: $decrypted decrypted, $skipped skipped"
}

# Resolve which stack owns a service directory by grepping its .env reference
# in committed stack files.  Uses linear scan (3 stacks × ~10 dirs) to stay
# POSIX-safe; avoids Bash 4+ associative arrays that break on macOS.
_dir_to_stack() {
	local rel_path="$1"
	for stack in "${STACK_FILES[@]}"; do
		local stack_file
		if stack_file="$(find_stack_file "$stack")"; then
			if grep -F "./${rel_path}/.env" "$stack_file" >/dev/null 2>&1; then
				printf '%s' "$stack"
				return 0
			fi
		fi
	done
	return 1
}

_secrets_deploy() {
	local -a dirs=("$@")
	local deployed=0
	local skipped=0

	# Decrypt all target services first (temp file + umask 077 + atomic move)
	local -a decrypted_dirs=()
	for dir in "${dirs[@]}"; do
		local enc_file="$dir/.env.enc"
		local env_file="$dir/.env"

		if [[ ! -f "$enc_file" ]]; then
			log "SKIP: $dir — no .env.enc file"
			skipped=$((skipped+1))
			continue
		fi

		log "Decrypting: $enc_file → $env_file"
		local tmp_env
		tmp_env="$(mktemp "${env_file}.tmp.XXXXXXXXXX")"
		local decrypt_ok=false
		if ( umask 077; sops --decrypt --input-type dotenv --output-type dotenv "$enc_file" > "$tmp_env" ); then
			mv "$tmp_env" "$env_file"
			decrypt_ok=true
			decrypted_dirs+=("$dir")
		else
			err "Failed to decrypt $enc_file — skipping deploy for this service"
			rm -f "$tmp_env"
			skipped=$((skipped+1))
		fi
	done

	# Determine which stacks to deploy (deduped, one lookup per dir)
	local -a stacks_to_deploy=()
	for dir in "${dirs[@]}"; do
		local rel_path="${dir#$SCRIPT_DIR/}"
		local stack
		if stack="$(_dir_to_stack "$rel_path")"; then
			# Deduplicate — same stack may be referenced by multiple services
			local already=false
			for s in "${stacks_to_deploy[@]}"; do
				[[ "$s" == "$stack" ]] && already=true
			done
			if [[ "$already" = false ]]; then
				stacks_to_deploy+=("$stack")
			fi
		else
			log "NOTE: $rel_path not found in any stack file — will decrypt but not deploy"
		fi
	done

	if [[ ${#stacks_to_deploy[@]} -gt 0 ]]; then
		# Regenerate stacks if needed (reuse up logic)
		if command -v python3 >/dev/null 2>&1; then
			log "Regenerating stacks before deploy..."
			python3 "$SCRIPT_DIR/tools/generate_stacks.py" || log "Warning: stack generation failed"
		fi

		for stack in "${stacks_to_deploy[@]}"; do
			local file
			if file="$(find_stack_file "$stack")"; then
				local render_file
				render_file="$(render_stack_file "$file")"
				log "Deploying stack: $stack"
				docker stack deploy -c "$render_file" "$stack"
				deployed=$((deployed+1))
			else
				err "Stack file not found for '$stack'"
			fi
		done
	else
		log "No stacks to deploy (services not found in any stack file)"
	fi

	# Shred only .env files that were successfully decrypted in this run
	if [[ ${#decrypted_dirs[@]} -gt 0 ]]; then
		log "Cleaning up plaintext .env files..."
		for dir in "${decrypted_dirs[@]}"; do
			local env_file="$dir/.env"
			if [[ -f "$env_file" ]]; then
				if command -v shred >/dev/null 2>&1; then
					shred -u "$env_file"
				else
					rm -f "$env_file"
					log "Warning: shred not available, used rm -f for $env_file"
				fi
			fi
		done
	fi

	log "Deploy complete: $deployed stack(s) deployed, $skipped skipped"
}

_secrets_clean() {
	local -a dirs=("$@")
	local cleaned=0

	for dir in "${dirs[@]}"; do
		local env_file="$dir/.env"
		local enc_file="$dir/.env.enc"

		if [[ -f "$env_file" && -f "$enc_file" ]]; then
			log "Shredding: $env_file"
			if command -v shred >/dev/null 2>&1; then
				shred -u "$env_file"
			else
				rm -f "$env_file"
				log "Warning: shred not available, used rm -f for $env_file"
			fi
			cleaned=$((cleaned+1))
		fi
	done

	log "Clean complete: $cleaned plaintext .env file(s) removed"
}

# Determine subcommand (default: up)
SUBCOMMAND="${1:-}"
case "$SUBCOMMAND" in
	up|down|status|logs|doctor|env|secrets|generate|sync|help|-h|--help)
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
	secrets)
		cmd_secrets "$@" ;;
	help|-h|--help)
		print_usage ;;
	*)
		err "Unknown command: $SUBCOMMAND"; print_usage; exit 2 ;;
esac

exit 0
