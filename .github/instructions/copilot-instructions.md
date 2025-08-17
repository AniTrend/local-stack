---
applyTo: **
description: Copilot instructions for Local-Stack repository
---

## Copilot instructions for Local-Stack repository

Goal: help an automated coding agent become productive quickly by describing the architecture, common developer workflows, repository conventions, and where to make safe, minimal changes.

1) Big-picture architecture
- This repo is a Docker Compose based local infrastructure for the AniTrend stack. Major service groups live in top-level folders: `traefik/`, `apisix/`, `observability/`, `postgres/`, `mongo/`, `redis/`, `growthbook/`, `portainer/`, `anitrend/`, and `on-the-edge/`.
- Traefik acts as the edge router and TLS terminator. Most services are fronted via subdomains (e.g. `grafana.localhost`, `apisix.localhost`) and configured under `traefik/config`.
- Observability is in `observability/` and contains `grafana/`, `prometheus/`, `loki/`, `tempo/`, `otel/` subfolders with their own compose files and provisioning configs.

2) Key files and conventions (referenced in tasks)
- Compose files: search for `**/docker-compose*.yml` or `**/docker-compose*.yaml`. Each service folder usually contains a compose file and an accompanying `.env.example`.
- Environment files: the repo expects service-specific `.env` files created from `.env.example` (e.g., `traefik/.env.example`). CI jobs often copy `.env.example` -> `.env` for validation.
- Traefik config: `traefik/config/traefik.yml` and `traefik/config/dynamic.yml` are authoritative for routing. When changing hostnames or ports update these files.
- Observability provisioning: `observability/grafana/config/provisioning/` contains dashboards and datasources that should be updated together with any metric source changes.

3) Developer workflows and commands (explicit)
- Start core stack locally (recommended order):
  - `cd traefik && cp .env.example .env && docker-compose up -d`
  - `cd ../postgres && docker-compose up -d` (then `mongo`, `redis`)
- Start observability stack:
  - `cd observability && for d in grafana prometheus loki tempo otel; do cp $d/.env.example $d/.env; done && docker-compose up -d`
- Validate compose files (what CI does):
  - `docker compose -f <path> config` (fails if unresolved variables or invalid syntax)
  - YAML linting: `yamllint <file>`
  - Dockerfile linting: run hadolint via container: `docker run --rm -v "$(pwd):/workdir" hadolint/hadolint hadolint <Dockerfile>`

4) What to change and where (safe-scoped edits)
- For configuration changes limited to one service, edit that service's `docker-compose.yml`, `.env.example`, and any config under its folder (e.g., `observability/grafana/config`).
- For cross-cutting network or hostname changes, update `traefik/config/dynamic.yml` and any service labels that define `traefik.http.routers`.
- Avoid changing `swarm.*.yml` files unless implementing swarm deployments — these are separate from the default Compose development flow.

5) Integration points and external dependencies
- Services communicate over Docker networks created by Compose. Many services expect Traefik to provide host-based routing and TLS.
- External dependencies: none hard-coded — services are brought up locally; however some components expect valid certificates in `traefik/certs` or secrets set in `.env` files.

6) Common pitfalls and agent guidance
- Do not assume `.env` files exist — CI copies `.env.example` to `.env` for validation. If making changes that introduce required env vars, add them to the corresponding `.env.example` and update README instructions.
- When editing Compose files, run `docker compose config` locally on the changed file to catch interpolation and syntax errors.
- When updating observability dashboards or Prometheus scrape configs, update the provisioning files in `observability/*/config` and include any new data sources in Grafana provisioning.

7) Code and content patterns to preserve
- Compose files use service-level folders; keep related config in the same folder.
- Many services mount local folders and volumes. Preserve relative paths and `volumes:` definitions — they are intentionally used for local dev persistence.

8) Where to run tests/builds
- There are no application unit tests in this repo; validation is primarily through Compose validation and scanning workflows (`.github/workflows/docker-lint.yml` and `.github/workflows/docker-scan.yml`).

9) If you are unsure
- Prefer small, reversible edits: add a new compose file or a separate example under the service folder and update README. Open a PR with CI results and request a human review.

If anything above is unclear or you want examples added (e.g., exact `docker compose config` output handling), tell me which area to expand and I'll iterate.
