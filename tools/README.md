# Compose Renderer

This tool renders Docker Compose/Stack YAML files by interpolating `${VAR}` references using per-service `env_file` and `environment` values.

Why: `docker stack deploy` only interpolates variables from the shell environment or a root `.env` file. It does not load variables from service-level `env_file` for interpolation (e.g., in labels/command/healthcheck). This renderer bridges that gap.

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r tools/requirements.txt
```

## Usage

```sh
# Render a stack file; output keeps docker-compose.* prefix under .rendered/
python3 tools/render_compose.py -i stacks/infrastructure.yml -o .rendered/docker-compose.infrastructure.rendered.yml
```

Then use the rendered file for validation or deployment:

```sh
docker compose -f .rendered/docker-compose.infrastructure.rendered.yml config
# or
docker stack deploy -c .rendered/docker-compose.infrastructure.rendered.yml infrastructure
```

## Behavior

- Interpolates strings recursively across the YAML document.
- Supports `${VAR}`, `${VAR-default}` (default when unset), and `${VAR:-default}` (default when unset or empty).
- Variable precedence per service:
  1. Current shell environment
  2. Values from service `env_file` (one or many)
  3. Values from service `environment`
- Leaves unresolved variables as-is by default. Use `--strict` to error if any remain.

## Limitations

- This is a preprocessing step; paths remain relative to the original file location.
- It does not evaluate command substitutions or complex expressions, only variable substitution.
