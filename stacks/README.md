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
