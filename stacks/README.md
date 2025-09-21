# Local-Stack Swarm Stacks

This folder contains the modular Docker Swarm stacks for the Local-Stack project.

## Stacks

- `infrastructure.yml`: Traefik, Portainer, APISIX (gateway + etcd + dashboard), Postgres, Mongo, Redis
- `observability.yml`: Prometheus, Grafana, Loki, Tempo, OTel Collector
- `platform.yml`: GrowthBook (dashboard + proxy), AniTrend apps/services

## Conventions

- Shared overlay network: `traefik-public` (external, attachable). Create once per swarm host.
- No Compose-only keys: do not use `container_name`, `restart`, or `build` in stacks.
- Use `deploy` for scheduling (mode, placement, resources) and `env_file` for configuration.
- All exposed services must attach to `traefik-public` and define Traefik labels for routing.
- Persist critical data via named volumes. Mark volumes as `external: true` to reuse existing data.

## Runbook (single-node)

```bash
# 1) Initialize Swarm (idempotent)
docker swarm init

# 2) Create shared overlay network (idempotent)
docker network create --driver=overlay --attachable traefik-public

# 3) Deploy stacks (names are identifiers)
docker stack deploy -c stacks/infrastructure.yml infrastructure
docker stack deploy -c stacks/observability.yml observability
docker stack deploy -c stacks/platform.yml platform

# 4) Verify
docker stack services infrastructure
docker stack services observability
docker stack services platform

# 5) Teardown (keeps volumes)
docker stack rm platform
docker stack rm observability
docker stack rm infrastructure
```

## Notes

- Ensure each service folder has a `.env` copied from its `.env.example` where applicable.
- APISIX dashboard uses `apisix/api-dashboard/config/conf.yaml` (generated from `conf.example.yml`).
- Consider adding healthchecks for critical dependencies to improve startup reliability.

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
