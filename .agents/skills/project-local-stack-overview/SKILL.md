---
name: project-local-stack-overview
description: Use when onboarding to the Local-Stack repo, locating the owning service or stack for a change, or checking Swarm migration conventions before editing infrastructure files
metadata:
  migrated-from: .github/instructions/project-context.instructions.md
  source-format: .instructions.md
---

# Project Local-Stack Overview

## Overview

Local-Stack is a local infrastructure repo moving from service-local Compose files to modular Docker Swarm stacks. Prefer the owning service directory for edits, then regenerate or sync derived stack output instead of patching generated files directly.

## When to Use

- Before changing infrastructure and needing the owning folder or stack.
- When deciding whether a change belongs in a service-local Compose file, a Swarm fragment, or generated stack output.
- When validating project conventions for Traefik exposure, shared networking, persistence, or Swarm deployment.
- When onboarding into the repo and needing a fast map of services and stacks.

## Core Pattern

1. Find the owning source folder first.
2. Edit service-local sources: `docker-compose.yml` for Compose concerns (image, volumes, labels); `swarm.fragment.yml` for Swarm-only config (`deploy`, network aliases, DNS overrides); `.env.example` for new variables.
3. Treat files under `stacks/` as rendered output unless the workflow explicitly says to regenerate or sync them.
4. Keep exposed services on the shared `traefik-public` network with Traefik labels.
5. Keep secrets out of source and prefer environment variables or documented secret management.

## Quick Reference

| Area | Source of truth | Notes |
| --- | --- | --- |
| Edge routing | `traefik/` | Main reverse proxy and shared entrypoint |
| API gateway | `apisix/` | Gateway, dashboard, and etcd live here |
| Databases | `postgres/`, `mongo/`, `redis/` | Persistent internal services |
| Observability | `observability/` | Grafana, Prometheus, Loki, Tempo, OTel |
| Platform apps | `growthbook/`, `anitrend/`, `on-the-edge/`, `edge-graphql/`, `website/`, `beszel/` | Service-local config and fragments |
| Generated stacks | `stacks/` | Do not hand-edit rendered output |

## Stack Mapping

| Stack | Main contents |
| --- | --- |
| `stacks/infrastructure.yml` | Traefik, Portainer, APISIX, Postgres, Mongo, Redis |
| `stacks/observability.yml` | Prometheus, Grafana, Loki, Tempo, OTel |
| `stacks/platform.yml` | GrowthBook and app-facing platform services |

## Common Commands

```bash
docker swarm init
docker network create --driver=overlay --attachable traefik-public
docker stack deploy -c stacks/infrastructure.yml infrastructure
docker stack deploy -c stacks/observability.yml observability
docker stack deploy -c stacks/platform.yml platform
```

## Common Mistakes

- Editing files under `stacks/` directly instead of the owning service source.
- Using deprecated root-level `swarm.*.yml` files for deployment.
- Forgetting the shared `traefik-public` network or required Traefik labels on exposed services.
- Treating `.env` files as guaranteed to exist instead of updating `.env.example` when new variables are needed.
- Adding Compose-only keys to Swarm output without checking Swarm compatibility.

## See Also

- [AGENTS.md](../../../AGENTS.md)
- [stacks/README.md](../../../stacks/README.md)
- [docs/Managing Secrets.md](../../../docs/Managing%20Secrets.md)
