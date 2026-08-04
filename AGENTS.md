# Local-Stack Agent Guide

Local-Stack is migrating from per-service Compose to modular Docker Swarm stacks. Keep agent guidance short, link to the canonical docs, and prefer editing the owning service or stack source instead of duplicating context here.

## Source Of Truth

- Service folders are the source of truth for config: `traefik/`, `apisix/`, `observability/`, `postgres/`, `mongo/`, `redis/`, `growthbook/`, `unleash/`, `portainer/`, `anitrend/`, `on-the-edge/`, `edge-graphql/`, `website/`, and `beszel/`.
- Generated Swarm stacks live in `stacks/`. Do not edit the generated stack output directly; regenerate with `stackctl generate` or, on the compatibility path, `./stackctl.sh generate`. Drift between compose sources and committed stacks is validated with `stackctl sync` (drift check only: it never generates or deploys). See [stacks/README.md](stacks/README.md).
- Deprecated root-level `swarm.*.yml` files are not used for deployment.

## How To Work

- For full-environment deploys and validation, follow [stacks/README.md](stacks/README.md) and prefer the `stackctl` CLI (configured by the committed `.stackctl`). Root `./stackctl.sh` is retained only as a compatibility fallback for the current Doco-CD Linux runtime.
- For service-local changes, update the service folder's `docker-compose.yml`, `swarm.fragment.yml`, and `.env.example` together when needed.
- **Swarm customizations go in `swarm.fragment.yml`:** `deploy` (mode, replicas, placement, resources), network aliases, DNS overrides, and any key that only applies under `docker stack deploy`. Keep `docker-compose.yml` portable — it should work standalone with `docker compose up` where possible.
- Keep exposed services attached to the shared `traefik-public` network and route them with Traefik labels and [traefik/config/dynamic.yml](traefik/config/dynamic.yml).
- Update Grafana provisioning under [observability/grafana/config/provisioning/](observability/grafana/config/provisioning/) when dashboards or datasources change.

## Project Skills

- [project-local-stack-overview](.agents/skills/project-local-stack-overview/SKILL.md) for repo structure, stack ownership, and Swarm migration context.
- [project-stackctl-changes](.agents/skills/project-stackctl-changes/SKILL.md) for stack orchestration changes (preferred `stackctl` CLI and the `stackctl.sh` compatibility path).
- [project-tools-python-utilities](.agents/skills/project-tools-python-utilities/SKILL.md) for Python utility changes under `tools/`.

## Change Rules

- Prefer pinned GHCR tags; avoid `latest`.
- Do not assume `.env` files exist. If a new variable is needed, update the matching `.env.example`.
- For edge-facing apps, include Traefik router/service labels and a healthcheck that matches the exposed endpoint.
- Keep secrets out of source; prefer environment variables and the guidance in [docs/Managing Secrets.md](docs/Managing%20Secrets.md).

## Good Starting Docs

- [README.md](README.md)
- [stacks/README.md](stacks/README.md)
- [docs/Managing Secrets.md](docs/Managing%20Secrets.md)
- [docs/Migrating Compose Files to a Modular Docker Swarm  2738a21416308060a700fda5cdcc3b2d.md](docs/Migrating%20Compose%20Files%20to%20a%20Modular%20Docker%20Swarm%20%202738a21416308060a700fda5cdcc3b2d.md)
