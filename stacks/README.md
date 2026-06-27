# Local-Stack Swarm Stacks

> **These files are generated artifacts.** Do not edit them directly.
> The source of truth is each service's `docker-compose.yml` (plus its `swarm.fragment.yml` for Swarm-specific config).
> To regenerate: `./stackctl.sh generate`
> To check for drift: `./stackctl.sh sync`

## Stacks

- `infrastructure.yml`: Traefik, Portainer, APISIX (gateway + etcd + dashboard), Postgres, Mongo, Redis
- `observability.yml`: Prometheus, Grafana, Loki, Tempo, OTel Collector
- `platform.yml`: GrowthBook (dashboard + proxy), AniTrend apps/services (`anitrend`, `on-the-edge`, `edge-graphql`)

## Conventions

- **Separation of concerns:** `docker-compose.yml` carries Compose-only concerns (`container_name`, `restart`, `build`, image, volumes, ports, labels). Swarm-specific customizations — `deploy` scheduling, network aliases, DNS overrides, and any key that only makes sense under `docker stack deploy` — belong in the sibling `swarm.fragment.yml`. Do not put Swarm config in `docker-compose.yml`.
- Shared overlay network: `traefik-public` (external, attachable). Create once per swarm host.
- No Compose-only keys: do not use `container_name`, `restart`, or `build` in stacks.
- Use `deploy` for scheduling (mode, placement, resources) and `env_file` for configuration.
- All exposed services must attach to `traefik-public` and define Traefik labels for routing.
- Persist critical data via named volumes. Mark volumes as `external: true` to reuse existing data.

## Runbook

### Using stackctl.sh (primary)

`./stackctl.sh` is the canonical deployment path. It handles preflight checks, stack
regeneration, variable rendering, and deployment in one workflow. Committed
`stacks/*.yml` files intentionally contain `${VAR}` placeholders that must be
resolved before Swarm can use them. `stackctl.sh` calls `tools/render_compose.py`
to substitute service-local `env_file` values into a gitignored `.rendered/`
copy, then deploys the rendered file.

Prerequisites:
- Docker Engine with Swarm enabled (single-node is fine)
- The external overlay network `traefik-public`
- Python render dependencies installed in `tools/.venv`
- Optional: local TLS certs in `traefik/certs/` for `*.docker.localhost`

Quick start:

```bash
# 0) Install the stack generation/render toolchain once per host
python3 -m venv tools/.venv
tools/.venv/bin/python -m pip install --upgrade pip
tools/.venv/bin/python -m pip install -r tools/requirements.txt

# 1) Validate your environment (safe to run repeatedly). Add --fix-network to auto-create the overlay network.
./stackctl.sh doctor --fix-network

# 2) Optionally ensure external named volumes exist before deploying
./stackctl.sh doctor --fix-volumes

# 3) Deploy all stacks and follow key logs (Traefik, Prometheus, Loki)
./stackctl.sh up

# Or deploy a subset
./stackctl.sh up -s infrastructure,observability

# Check status
./stackctl.sh status

# Tail logs for specific services
./stackctl.sh logs infrastructure_traefik observability_prometheus

# Remove stacks (keeps volumes); add --remove-network to also remove traefik-public
./stackctl.sh down -y

# For encrypted secrets, decrypt, render, deploy, and clean up in one step:
./stackctl.sh secrets deploy
```

Notes:
- `stackctl.sh` finds stack files from `stacks/*.yml`. The rendered output is written to `.rendered/` (gitignored); committed source stacks are never modified.
- The `doctor` command validates Compose syntax for each stack and reminds you to create `.env` files where a `.env.example` exists. For encrypted secrets, use `./stackctl.sh secrets deploy` instead (see [Managing Secrets](../docs/Managing%20Secrets.md)).
- If you use local HTTPS, make sure `traefik/certs/local-cert.pem` and `traefik/certs/local-key.pem` exist; see below for generation.
- To check for drift between compose sources and committed stacks: `./stackctl.sh sync`

### Raw docker stack deploy (alternative, advanced)

> **These commands deploy unresolved `${VAR}` placeholders.** Committed `stacks/*.yml`
> are not directly deployable without pre-rendering or equivalent shell environment
> setup. Docker Swarm does not load `env_file` for Compose variable interpolation --
> that is a Compose CLI feature only.

If you must deploy manually, ensure all variables are resolved first (e.g., via
`tools/render_compose.py` or `envsubst`). For debugging or inspection:

```bash
# 1) Initialize Swarm (idempotent)
docker swarm init

# 2) Create shared overlay network (idempotent)
docker network create --driver=overlay --attachable traefik-public

# 3) Generate stacks from compose sources
./stackctl.sh generate

# 4) Render variables into .rendered/ files
#    (handled automatically by stackctl.sh up; shown here for manual inspection)
python3 tools/render_compose.py -i stacks/infrastructure.yml -o .rendered/infrastructure.rendered.yml --repo-root .

# 5) Deploy the rendered file (not the source stack)
docker stack deploy -c .rendered/infrastructure.rendered.yml infrastructure

# 6) Verify
docker stack services infrastructure
docker stack services observability
docker stack services platform

# 7) Teardown (keeps volumes)
docker stack rm platform
docker stack rm observability
docker stack rm infrastructure
```

### Rendered output

`stackctl.sh` pre-renders variables into gitignored `.rendered/` copies before
deployment.  Naming follows `${stack_name}.rendered.yml`:

- `stacks/infrastructure.yml` → `.rendered/infrastructure.rendered.yml`
- `stacks/observability.yml` → `.rendered/observability.rendered.yml`
- `stacks/platform.yml` → `.rendered/platform.rendered.yml`

These files are ignored by Git and safe to regenerate at any time. Inspect without
committing:

```bash
./stackctl.sh up --dry-run  # validates and logs render paths
# or render manually:
python3 tools/render_compose.py -i stacks/infrastructure.yml -o /tmp/check.rendered.yml --repo-root .
```

## Notes

- Ensure each service folder has a `.env` available. For local development, copy from `.env.example`; for production, use `./stackctl.sh secrets deploy` (see [Managing Secrets](../docs/Managing%20Secrets.md)).
- APISIX dashboard uses `apisix/api-dashboard/config/conf.yaml` (generated from `conf.example.yml`).
- Healthchecks have been added for Prometheus and APISIX. Consider adding them for other services as needed.

### Resource caps & logging

- Stacks set conservative `deploy.resources` reservations/limits to avoid runaway memory/CPU. Adjust in ±128–256MiB steps based on telemetry.
- Services use the `local` logging driver with rotation (`max-size=10m`, `max-file=3`) to reduce JSON log churn. If you prefer a global default, set it in `/etc/docker/daemon.json` and restart Docker.

### Tuning highlights

- Prometheus: 3d retention (`--storage.tsdb.retention.time=3d`), `--query.max-concurrency=10`; scrape intervals relaxed to 30s for most jobs.
- Loki: retention 72h, chunk target ~1.5MiB, moderate ingestion rate, compactor retention enabled.
- Tempo: local backend with 48h retention from config; single-replica by default.
- GrowthBook: Node heap capped via `NODE_OPTIONS=--max-old-space-size=512`.
- Traefik: access logs disabled by default; enable temporarily if debugging.

### Troubleshooting

- Verify per-stack services: `docker stack services <stack>` and `docker service logs <stack>_<service>`.
- If Traefik can't reach a service, confirm it's attached to `traefik-public` and labels point to the correct `server.port` and host.
- For noisy logs or high disk writes, ensure the `local` driver is in effect and service-level logging options are applied.

## Local HTTPS for *.docker.localhost

For local development with HTTPS on domains like `grafana.docker.localhost`, Traefik is configured with a `local` certificatesResolver and a file provider for TLS certificates.

What this means:
- ACME/Let’s Encrypt will not issue for `.localhost` domains. Instead, generate a local development certificate and key, and place them in `traefik/certs/` as `local-cert.pem` and `local-key.pem`.
- The dynamic config (`traefik/config/dynamic.yml`) already references these files and declares the `docker.localhost` SANs, including `*.docker.localhost`.
- Set `CERT_RESOLVER=local` in `traefik/.env` (and any service labels that reference it) to use the local resolver while Traefik serves the file-based certs.

Generate a dev cert (example using mkcert):

```bash
mkcert -install
mkcert -cert-file traefik/certs/local-cert.pem -key-file traefik/certs/local-key.pem "docker.localhost" "*.docker.localhost"
```

Notes:
- `traefik/certs/.gitignore` prevents committing private keys or ACME storage files.
- Browsers trust mkcert’s local CA after `mkcert -install`. If not using mkcert, you may need to trust your self-signed CA manually.
