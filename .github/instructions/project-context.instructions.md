---
applyTo: **
description: Overview of Local-Stack, its structure, and the migration from multi-Compose to modular Docker Swarm stacks (infrastructure, observability, platform).
---
## Project Overview
Local-Stack is a comprehensive local development infrastructure. Historically it used multiple Docker Compose files per service; we are migrating to modular Docker Swarm stacks for declarative, single-command deployment across local and remote hosts. The stack includes databases, API gateways, observability tools, reverse proxies, and more, enabling production-like workflows locally.

## Project Structure
The project is organized into directories, each containing docker-compose files for different services:

```
local-stack/
├── LICENSE
├── README.md
├── swarm.infrastructure.yml     # Deprecated initial Swarm attempt (do not use)
├── swarm.observerability.yml    # Deprecated initial Swarm attempt (do not use)
├── anitrend/                    # AniTrend application specific configs
├── apisix/                      # API Gateway services
│   ├── api-dashboard/           # APISIX Dashboard
│   ├── api-gateway/             # APISIX Gateway
│   └── etcd/                    # etcd service for APISIX
├── growthbook/                  # Feature flag management
│   ├── dashboard/               # GrowthBook dashboard
│   └── proxy/                   # GrowthBook proxy
├── mongo/                       # MongoDB database
├── observability/               # Monitoring and observability services
│   ├── grafana/                 # Visualization and dashboards
│   ├── loki/                    # Log aggregation
│   ├── otel/                    # OpenTelemetry collector
│   ├── prometheus/              # Metrics collection and alerting
│   └── tempo/                   # Distributed tracing
├── on-the-edge/                 # Edge computing services
├── portainer/                   # Docker container management UI
├── postgres/                    # PostgreSQL database
├── redis/                       # Redis in-memory database
└── traefik/                     # Reverse proxy and edge router
    ├── auth/                    # Authentication configuration
    ├── certs/                   # SSL certificates
    └── config/                  # Traefik configuration
```

## Service Configuration

### Core Infrastructure

- **Traefik**: Acts as the main reverse proxy for all services
  - Configuration files: `traefik/config/traefik.yml` and `traefik/config/dynamic.yml`
  - Access: Default dashboard at `https://traefik.localhost`

- **Databases**:
  - **PostgreSQL**: Standard relational database
    - Configuration: `postgres/docker-compose.yaml`
    - Default port: 5432
  - **MongoDB**: Document database
    - Configuration: `mongo/docker-compose.yaml`
    - Default port: 27017
  - **Redis**: In-memory database
    - Configuration: `redis/docker-compose.yaml`
    - Default port: 6379

### API Gateway

- **APISIX**: API Gateway for managing APIs
  - Gateway configuration: `apisix/api-gateway/docker-compose.yml`
  - Dashboard configuration: `apisix/api-dashboard/docker-compose.yml`
  - Default access: `https://apisix.localhost`

### Observability Stack

- **Grafana**: Visualization dashboards
  - Configuration: `observability/grafana/docker-compose.yml`
  - Default access: `https://grafana.localhost`

- **Prometheus**: Metrics collection
  - Configuration: `observability/prometheus/docker-compose.yml`
  - Default access: `https://prometheus.localhost`

- **Loki**: Log aggregation
  - Configuration: `observability/loki/docker-compose.yml`

- **Tempo**: Distributed tracing
  - Configuration: `observability/tempo/docker-compose.yml`

- **OTel**: OpenTelemetry collector
  - Configuration: `observability/otel/docker-compose.yml`

### Management Tools

- **Portainer**: Docker container management
  - Configuration: `portainer/docker-compose.yml`
  - Default access: `https://portainer.localhost`

- **GrowthBook**: Feature flag management
  - Dashboard configuration: `growthbook/dashboard/docker-compose.yml`
  - Proxy configuration: `growthbook/proxy/docker-compose.yml`
  - Default access: `https://growthbook.localhost`

## Common Tasks

### Starting Services

Suggest appropriate commands to start services based on the developer's needs:

```bash
# Start the entire stack
docker-compose -f docker-compose.yml up -d

# Start specific services
cd postgres && docker-compose up -d
cd redis && docker-compose up -d
cd traefik && docker-compose up -d
```

### Setting Up Environment Variables

Help identify and create necessary `.env` files based on example files:

```bash
# For services that have .env.example files
cp .env.example .env
```

### Network Troubleshooting

Common issues include:
- Services unable to communicate with each other
- Port conflicts
- DNS resolution issues within Docker networks

Suggest commands to diagnose:
```bash
# Check network connectivity
docker network ls
docker network inspect traefik

# Check container logs
docker logs <container_name>

# Check container status
docker ps -a
```

### Accessing Services

All services are exposed through Traefik and accessible via subdomains:
- `https://traefik.localhost` - Traefik dashboard
- `https://grafana.localhost` - Grafana
- `https://prometheus.localhost` - Prometheus
- `https://apisix.localhost` - APISIX dashboard
- `https://portainer.localhost` - Portainer
- `https://growthbook.localhost` - GrowthBook

## Docker Swarm Deployment
We are migrating to three modular Swarm stacks. New stack files will live under `stacks/`:
- `stacks/infrastructure.yml`: Traefik, Portainer, APISIX (gateway, etcd, dashboard), Postgres, Mongo, Redis
- `stacks/observability.yml`: Prometheus, Grafana, Loki, Tempo, OTel Collector
- `stacks/platform.yml`: GrowthBook (dashboard, proxy), AniTrend apps/services, others

Shared network:
- All stacks attach to an external overlay network named `traefik-public`. Create it once per Swarm: `docker network create --driver=overlay --attachable traefik-public`.

Key Swarm conventions:
- Remove Compose-only keys (`container_name`, `restart`, `build`). Use `deploy` for mode, placement, resources, and restart policy.
- Use `env_file` for per-service configuration; consider Docker secrets/config for sensitive values.
- Use named volumes; mark as `external: true` to reuse existing data (e.g., Traefik certs, Portainer data, databases).
- `depends_on` provides order hints only; prefer healthchecks for readiness where critical.

Initial runbook (single-node Swarm):
```bash
# 1) Initialize Swarm (idempotent)
docker swarm init

# 2) Create shared network (idempotent)
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

Deprecated:
- Root-level `swarm.*.yml` files are deprecated and retained only for reference. Do not use them for deployments.

## Best Practices

- Always use environment variables for sensitive information
- Use Docker volumes for persistent data storage
- Check container health status with `docker ps` and container logs
- Use the Portainer UI for visual container management
- Configure proper resource limits in Docker Compose files

Swarm-specific:
- Prefer `deploy.mode: global` for singletons (e.g., Traefik, Portainer) and `placement.constraints` such as `node.role == manager` for core infra.
- For scalable/stateless components, use `deploy.mode: replicated` with `replicas`.
- Attach all exposed services to the `traefik-public` overlay network for routing.

## Common Issues and Solutions

1. **DNS Resolution**: Add proper DNS entries to `/etc/hosts` for local development
2. **SSL Certificates**: Generate self-signed certificates for development
3. **Service Startup Order**: Use `depends_on` in Docker Compose for dependent services
4. **Data Persistence**: Configure volumes properly to prevent data loss

Swarm migration tips:
- If a stack deploy fails with "unsupported options" errors, remove Compose-only keys and ensure images are pre-built or in a registry (no `build:` in stacks).
- If Traefik cannot route to services, confirm the service has labels and is attached to `traefik-public`.
- Re-run `docker stack deploy` after editing stack files; Swarm will apply changes in place.

## Component-to-Stack Mapping (implementation guide)

- Infrastructure stack (`stacks/infrastructure.yml`)
  - Traefik: attach to `traefik-public`; mount certs volume; keep existing labels; expose 80/443; manager-only, global.
  - Portainer: attach to `traefik-public`; mount data volume; label for UI route; manager-only, global.
  - APISIX Gateway: attach to `traefik-public`; mount config; labels for admin/UI as applicable; depends on etcd.
  - APISIX etcd: persistent volume for data; internal only; depended on by gateway and dashboard.
  - APISIX Dashboard: attach to `traefik-public`; labels for route; depends on gateway and Traefik (order only).
  - Postgres/Mongo/Redis: persistent named volumes; internal only (no Traefik labels) unless explicitly needed; manager-only, global or replicated=1.

- Observability stack (`stacks/observability.yml`)
  - Prometheus: mount config dir and data volume; labels for route; manager-only, global.
  - Grafana: mount data volume and provisioning; labels for route; depends_on prometheus/loki/tempo.
  - Loki: mount data volume; internal port only; optional route via labels if UI enabled.
  - Tempo: mount data volume; internal ports; optional route.
  - OTel Collector: mount config; depends_on loki/tempo/prometheus; internal only.

- Platform stack (`stacks/platform.yml`)
  - GrowthBook Dashboard: attach to `traefik-public`; labels for route; env_file; persistent volume if used.
  - GrowthBook Proxy: attach to `traefik-public`; labels; env_file.
  - AniTrend apps/services: attach to `traefik-public` if exposed; labels per route; env_file; prefer replicated for stateless services.

Conventions
- Networks: every exposed service must attach to the external `traefik-public` network.
- Volumes: define at top-level; mark `external: true` when reusing existing data (e.g., `traefik-ssl-certs`, `portainer-data`, database volumes).
- Env: load `env_file` from the corresponding service folder to keep configuration centralized.

## License

This project is licensed under the Apache License 2.0. Respect the license terms when modifying or redistributing the code.
