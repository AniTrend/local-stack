---
applyTo: **
description: Copilot instructions for Local-Stack repository
---

## Copilot instructions for Local-Stack repository

Goal: help an automated coding agent become productive quickly by describing the architecture, common developer workflows, repository conventions, and where to make safe, minimal changes.

1) Big-picture architecture
- Historically, this repo used multiple Docker Compose files per service. We are migrating to modular Docker Swarm stacks to deploy the environment declaratively across local and remote hosts.
- Service folders remain the source of truth for per-service configs: `traefik/`, `apisix/`, `observability/`, `postgres/`, `mongo/`, `redis/`, `growthbook/`, `portainer/`, `anitrend/`, and `on-the-edge/`.
- Traefik is the edge router/TLS terminator; routing and middleware live in `traefik/config` and service-level labels.
- Observability lives under `observability/` (`grafana/`, `prometheus/`, `loki/`, `tempo/`, `otel/`).
- Target stack split (Swarm):
  - Infrastructure: Traefik, Portainer, APISIX (gateway + etcd + dashboard), Postgres, Mongo, Redis.
  - Observability: Prometheus, Grafana, Loki, Tempo, OTel Collector.
  - Platform: GrowthBook (dashboard + proxy), AniTrend apps/services, and other application-facing components.

2) Key files and conventions (referenced in tasks)
- Compose files: search for `**/docker-compose*.yml` or `**/docker-compose*.yaml`. Each service folder usually contains a compose file and an accompanying `.env.example`.
- Environment files: the repo expects service-specific `.env` files created from `.env.example` (e.g., `traefik/.env.example`). CI jobs often copy `.env.example` -> `.env` for validation.
- Traefik config: `traefik/config/traefik.yml` and `traefik/config/dynamic.yml` are authoritative for routing. When changing hostnames or ports update these files.
- Observability provisioning: `observability/grafana/config/provisioning/` contains dashboards and datasources that should be updated together with any metric source changes.
- Swarm stacks: new modular Swarm stack files will live under a `stacks/` directory (planned names: `infrastructure.yml`, `observability.yml`, `platform.yml`). The legacy root-level `swarm.*.yml` files are deprecated—do not edit or use them.

3) Developer workflows and commands (explicit)
- Preferred (Swarm, modular):
  - Initialize Swarm (once per host): `docker swarm init`.
  - Create shared overlay network (once): `docker network create --driver=overlay --attachable traefik-public`.
  - Deploy stacks:
    - `docker stack deploy -c stacks/infrastructure.yml infrastructure`
    - `docker stack deploy -c stacks/observability.yml observability`
    - `docker stack deploy -c stacks/platform.yml platform`
  - Verify: `docker stack services <stack>` and Portainer UI. Tear down with `docker stack rm <stack>`.
- Legacy local-only (Compose): still available per service for iterative work until migration completes.
  - Example: `cd traefik && cp .env.example .env && docker compose up -d`
  - Observability (legacy): `cd observability && for d in grafana prometheus loki tempo otel; do cp $d/.env.example $d/.env; done && docker compose up -d`
- Validation (CI/dev):
  - Compose syntax: `docker compose -f <path> config`.
  - YAML linting: `yamllint <file>`.
  - Dockerfile linting: `hadolint` via container.

4) What to change and where (safe-scoped edits)
- Service-scoped config: edit the service folder (`docker-compose.yml`, `.env.example`, and config files) as before. These feed into both Compose and Swarm stacks.
- Swarm stacks (preferred for deployment): add/update files under `stacks/` to include or configure services. Keep stacks modular by function: infrastructure, observability, platform.
- Cross-cutting routing or hostnames: update `traefik/config/dynamic.yml` and service labels (`traefik.http.routers.*`).
- Do NOT edit or use root-level `swarm.*.yml`—they are deprecated remnants of an initial attempt.

5) Integration points and external dependencies
- Networks: Under Swarm, all exposed services attach to a shared external overlay network named `traefik-public` (create once). Compose continues to create local bridge networks for ad-hoc local runs.
- Routing: Traefik discovers services via Docker metadata and labels on the shared network.
- External dependencies: none hard-coded; some components expect valid certificates in `traefik/certs` and secrets via `.env`.

6) Common pitfalls and agent guidance
- Ensure the external overlay network `traefik-public` exists before deploying stacks.
- Avoid Compose-only keys in Swarm stacks: no `container_name`, no `restart` (use `deploy.restart_policy`), and no `build` (images must be pre-built/pulled).
- Prefer `deploy` settings in Swarm: `mode` (global/replicated), `placement.constraints` (e.g., `node.role == manager`), resource limits, and optional `restart_policy`.
- Use `env_file` to load per-service `.env`; consider Docker secrets/config for sensitive values in future iterations.
- `depends_on` in Swarm affects start order only; add healthchecks for critical readiness if needed.
- Do not assume `.env` files exist; if adding new variables, update `.env.example` and docs.
- When updating observability dashboards or Prometheus scrape configs, update provisioning under `observability/*/config` and Grafana datasources.

7) Code and content patterns to preserve
- Service-level folder structure; keep related config colocated.
- Volume mounts and named volumes for persistence.
- Traefik labels on services for routing; keep consistent naming and middleware reuse.

8) Where to run tests/builds
- There are no application unit tests in this repo; validation is through Compose validation and scanning workflows (`.github/workflows/docker-lint.yml` and `.github/workflows/docker-scan.yml`).
- For Swarm changes, perform a dry deploy on a local single-node swarm and verify `docker stack services` shows healthy tasks; prefer incremental stack updates.

9) If you are unsure
- Prefer small, reversible edits: add/update `stacks/<module>.yml` rather than touching many service configs at once. Keep Compose changes minimal and documented.
- Open a PR with CI results and a brief manual verification plan (Swarm deploy steps and expected endpoints).

10) Acceptance criteria for the Swarm migration (initial phase)
- Single-node Swarm deploys of `infrastructure`, `observability`, and `platform` stacks succeed.
- All exposed services are reachable via Traefik on the shared `traefik-public` network.
- No Swarm stack uses `container_name`, `restart`, or `build` keys.
- Critical data volumes (e.g., Traefik certs, Portainer data, databases) are persisted via named volumes (external where reusing existing data).

Deprecated: root-level `swarm.*.yml` files. Do not use or update; they will be archived once new `stacks/*.yml` files are introduced.

If anything above is unclear or you want examples added (e.g., exact `docker compose config` output handling), tell me which area to expand and I'll iterate.
