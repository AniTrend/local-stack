# Doco-CD Setup Feedback

## Current state

`doco-cd/` is now integrated into the `platform` stack. The source Compose declares `x-stack: platform`, consumes `.env` through `env_file`, carries full Traefik routing labels, joins the Traefik network, and has log rotation plus a Swarm fragment with manager placement and resource caps.

Evidence:

- `doco-cd/docker-compose.yml:2` declares `x-stack: platform`, so `tools/generate_stacks.py:330-354` discovers the file and emits it into `stacks/platform.yml`.
- `doco-cd/docker-compose.yml:5` pins `ghcr.io/kimdre/doco-cd:0.105.0`.
- `doco-cd/docker-compose.yml:9` declares `env_file: .env`; `doco-cd/.env.example:1-4` documents `TRAEFIK_ENABLE=false`, `CERT_RESOLVER=local`, `PORT=8088`, and `HOST=doco.docker.localhost`.
- `doco-cd/docker-compose.yml:10-18` defines the Traefik router `doco` (host rule, `web,websecure` entrypoints, TLS with `${CERT_RESOLVER}`), the load balancer server port `${PORT}`, and `traefik.http.services.doco.loadbalancer.healthcheck.path=/health`.
- `doco-cd/docker-compose.yml:46-48` attaches the service to the external `traefik` network in source form; the generator rewrites the stack network to `traefik-public` per `tools/generate_stacks.py:317-323`.
- `doco-cd/docker-compose.yml:20-24` configures the `local` logging driver with `max-size: 10m` and `max-file: 3`.
- `doco-cd/docker-compose.yml:25-29` keeps polling enabled via inline `POLL_CONFIG` (`refs/heads/dev`, 300s), matching `doco-cd/README.md:41-48`.
- `doco-cd/swarm.fragment.yml:7-20` adds Swarm-only settings: `mode: global`, `node.role == manager` placement, restart policy, and 96M/0.10 to 384M/0.50 memory/CPU caps, following `AGENTS.md:13-16` and `stacks/README.md:14-21`.
- The merged result is visible at `stacks/platform.yml:13-56`: the doco-cd service with the fragment's deploy block, network alias, rewritten `env_file: ./doco-cd/.env`, and the `/health` healthcheck label.

## Remaining gaps and risks

Based on current evidence only:

1. Generated stack drift (confirmed, separate from Doco-CD). Commit `7e6f882` commented out the `anitrend-edge` healthcheck in `on-the-edge/docker-compose.yaml:19-24`, but the committed `stacks/platform.yml` still carried that stale healthcheck block. The regenerated working tree removes it. This is a generated output synchronization issue: use `./stackctl.sh sync` to detect similar drift, and `./stackctl.sh generate` to update the output. Never hand-edit `stacks/`, per `AGENTS.md:5-9` and `stacks/README.md:1-7`.
2. Traefik endpoint contract unvalidated. The load balancer healthcheck points at `/health` and the server port is `${PORT}` (default 8088), while the earlier baseline mapped host 8088 to container 80. Confirm what port image 0.105.0 actually listens on inside the container and that it serves `/health`; adjust `PORT` or the label if the container port differs.
3. Docker container `healthcheck:` is still not declared for `doco-cd`. The Traefik load balancer healthcheck label is present, so this is a task-level visibility nicety, not a routing blocker.
4. `.env` must exist for `env_file: .env` to have effect, and only `POLL_CONFIG` is set in `environment:`; `TZ`, `WEBHOOK_SECRET_FILE`, and `API_SECRET_FILE` from `doco-cd/.env.example:7-17` are wired only if the operator creates `.env` from the example. `TRAEFIK_ENABLE=false` in the example also means the router stays disabled unless explicitly enabled.
5. Secret bootstrap caveat (unchanged): `doco-cd/docker-compose.yml:37-41` reads `./secrets/webhook_secret` and `./secrets/api_secret` from the local filesystem at deploy time, and `doco-cd/.gitignore` excludes `secrets/`. This works for the current single-node setup but is separate from the `./stackctl.sh secrets deploy` SOPS flow used by stack services; see `docs/Managing Secrets.md`.

## Decision path 1: keep polling-only by default

Polling remains the default and works without inbound traffic, consistent with `doco-cd/README.md:41-48`. The Traefik labels now exist, so the only remaining question is whether `TRAEFIK_ENABLE=false` should stay the default.

Recommendations:

1. Validate the `/health` contract (path and container port) against the pinned image before enabling the router.
2. Keep `TRAEFIK_ENABLE=false` unless webhook delivery is actually needed; when enabling, set `HOST`, `CERT_RESOLVER`, and `PORT` in `doco-cd/.env` per `doco-cd/.env.example:1-4`.
3. Optionally add a Docker container `healthcheck:` hitting `/health` for task-level visibility, mirroring the `unleash` and `growthbook` patterns in `stacks/platform.yml`.
4. Keep local file secrets documented as the bootstrap split. Do not force the bootstrap controller into the SOPS flow unless the maintainer decides it should be managed like other stack services.

Severity under this model:

- High: none identified from the reviewed files.
- Medium: `/health` and the container port are unvalidated against image 0.105.0; `.env` creation is now required for the secret env vars to be wired.
- Low: no Docker container `healthcheck:` for `doco-cd`; the Traefik load balancer healthcheck label already covers routing.

## Decision path 2: expose webhooks through Traefik

The ingress pieces are now in place: labels at `doco-cd/docker-compose.yml:10-18`, the source external network at `doco-cd/docker-compose.yml:46-48` (rewritten to `traefik-public` in the generated stack), and router `doco` covering all paths, including `/v1/webhook`, once enabled. What remains is validation, not construction.

Remaining validation:

1. Deploy and confirm actual network behavior: Traefik's Docker provider discovers the `doco` router, the overlay network is attachable, and `curl https://doco.docker.localhost/health` (or the chosen `HOST`) returns 200. Note `docker compose` uses the source `traefik` network while `docker stack deploy` uses `traefik-public`; see `stacks/README.md:17-20` and `AGENTS.md:16`.
2. Confirm `/health` is the correct endpoint for the current Doco-CD image and that `${PORT}` matches the container's listening port (see gaps above). Fix the label or `.env` if not.
3. Revisit `doco-cd/README.md:69-73`. Exposing `/v1/webhook` through Traefik means the webhook secret and any router middleware (for example IP allowlisting) become part of the ingress decision. The webhook URL in `doco-cd/README.md:51` includes host port 8088; that host port only applies if a `ports:` mapping is added, otherwise Traefik routes on the container port directly.
4. Decide defaults: `TRAEFIK_ENABLE=false`, `CERT_RESOLVER=local`, `HOST=doco.docker.localhost` at `doco-cd/.env.example:1-4`.

Severity under this model:

- High: none; labels and network wiring are present.
- Medium: endpoint contract (`/health` and container port) unvalidated for image 0.105.0; runtime discovery not yet exercised.
- Low: router and service name `doco` is fixed; renaming later means updating labels in both the source and the generated stack.

## Decision path 3: keep Doco-CD stack-managed

Stack integration is now present rather than missing: `x-stack: platform` at `doco-cd/docker-compose.yml:2`, `doco-cd/swarm.fragment.yml` with manager placement and resource caps, and the generated service at `stacks/platform.yml:13-56`. The decision is whether to keep this or revert to a host-level bootstrap controller.

Tradeoffs:

1. Self-referential deployment: Doco-CD is the controller that triggers deployments of the `platform` stack that includes it. Failure recovery and first install become more coupled, because the tool that repairs the stack is inside the stack. A host-level bootstrap controller is simpler for initial deployment and recovery. If that model is preferred, drop `x-stack:` and `swarm.fragment.yml` and keep the manual bootstrap flow at `doco-cd/README.md:10-30`.
2. Generator effects apply: `container_name` and `restart` are stripped (`tools/generate_stacks.py:56-64`), `env_file` is rewritten repo-root relative (`tools/generate_stacks.py:158-182`), logging defaults are injected when absent (`tools/generate_stacks.py:117-127`), named volumes become external, and the stack network becomes `traefik-public` (`tools/generate_stacks.py:317-323`).
3. Secrets: keep local file secrets as documented, or join the SOPS flow after the bootstrap model is settled.

Severity under this model:

- High: none; integration exists.
- Medium: self-referential bootstrap coupling for recovery and first install.
- Low: none beyond the secrets split.

## Maintainer decisions needed

1. Should Doco-CD remain polling-only with `TRAEFIK_ENABLE=false`, or be exposed by default?
2. Validate the endpoint contract for image 0.105.0: which port does it listen on inside the container, and is `/health` served there?
3. If Traefik exposure is desired, confirm `HOST=doco.docker.localhost`, `CERT_RESOLVER=local`, and whether `/v1/webhook` needs middleware.
4. Should `.env` be created from `.env.example` now that `env_file: .env` is declared, and should `TZ` and the secret file env vars stay operator-managed?
5. Keep Doco-CD stack-managed, or revert to a host-level bootstrap controller?
6. Should Doco-CD bootstrap secrets remain local Docker secret files, or later join the SOPS workflow after the bootstrap model is settled?
7. Regenerate and commit `stacks/platform.yml` with `./stackctl.sh generate` to clear the `anitrend-edge` healthcheck drift, as a separate generated-output sync fix.
