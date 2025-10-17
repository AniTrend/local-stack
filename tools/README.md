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

## Overlays (environment-specific overrides)

For multi-environment deployments you can provide small, focused overlay YAML files that are deep-merged
onto the base `stacks/<stack>.yml` before interpolation. Overlays live under `environments/<env>/` and are
named `<stack>.overlay.yml` (or `.yaml`). Example overlay path:

```
environments/local/infrastructure.overlay.yml
environments/staging/infrastructure.overlay.yml
environments/prod/infrastructure.overlay.yml
```

How overlays are applied:
- The renderer first loads the base stack file from `stacks/<stack>.yml`.
- If an overlay exists, it is deep-merged into the base (nested mappings are merged, simple scalars/lists are replaced).
- The merged YAML is then passed to `tools/render_compose.py` which resolves `${VAR}` using service `env_file`s and environment.

Simple examples

1) Change Traefik host and TLS resolver for local testing (environments/local/infrastructure.overlay.yml):

```yaml
services:
  traefik:
    environment:
      HOST: "traefik.localhost"
      CERT_RESOLVER: "local"

  grafana:
    environment:
      HOST: "grafana.localhost"
```

2) Point APISIX gateway to a local etcd for dev (environments/local/infrastructure.overlay.yml):

```yaml
services:
  apisix:
    environment:
      ETCD_HOSTS: "http://etcd:2379"
      APISIX_ENABLE_PROMETHEUS: "true"

  etcd:
    volumes:
      - etcd-data:/var/lib/etcd

volumes:
  etcd-data:
    driver: local
```

3) Production override example (environments/prod/infrastructure.overlay.yml):

```yaml
services:
  traefik:
    environment:
      HOST: "traefik.example.com"
      CERT_RESOLVER: "letsencrypt"
    deploy:
      placement:
        constraints:
          - node.role == manager

  apisix:
    environment:
      ETCD_HOSTS: "https://etcd.prod.internal:2379"
    deploy:
      replicas: 3

volumes:
  etcd-data:
    external: true
```

Using overlays with the Python CLI

Render and deploy a stack with the `local` overlay:

```sh
python3 tools/stackctl_cli.py deploy --stacks infrastructure --env local
```

Or render only (writes to `./.rendered`):

```sh
python3 tools/stackctl_cli.py render --stacks infrastructure --env local
```

Notes and tips
- Keep overlays small and focused: change only the values that differ between environments.
- Use overlays to drive Traefik hostnames, TLS settings, resource constraints, and scaling hints.
- For secrets, prefer encrypted files (SOPS) and use `tools/stackctl_cli.py secrets decrypt` during local setup.

