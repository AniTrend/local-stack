# Doco-CD Setup Feedback

## Current state

`doco-cd/` is currently configured as a host-level bootstrap controller, with polling enabled by default and local-only HTTP binding.

Evidence:

- `doco-cd/docker-compose.yml:3-24` defines one `doco-cd` service using `ghcr.io/kimdre/doco-cd:0.101.1`, `127.0.0.1:8088:80`, Docker socket access, file secrets, inline `POLL_CONFIG`, and only the private `doco-private` network.
- `doco-cd/README.md:41-48` describes polling as the default and recommended mode, with no inbound endpoint required.
- `doco-cd/README.md:49-60` describes webhooks as optional and compatible with polling.
- `doco-cd/README.md:75-81` states that external webhook delivery needs a reverse proxy, tunnel, or polling-only operation.
- `doco-cd/docker-compose.yml` has no Traefik labels, no shared ingress network, no `env_file`, no Docker container `healthcheck:`, no logging rotation block, and no `x-stack:`.
- `doco-cd/.env.example:1-15` documents `TZ` and secret generation, but `doco-cd/docker-compose.yml` does not declare `env_file: .env` or interpolate those example values. `TZ` is hardcoded at `doco-cd/docker-compose.yml:10`.

## Decision path 1: keep polling-only bootstrap

If the intended operating model is polling-only bootstrap, the current lack of Traefik exposure is not a defect. It is aligned with `doco-cd/README.md:41-48` and the local bind at `doco-cd/docker-compose.yml:7-8`.

Minimum cleanup recommendations:

1. Add a Docker container `healthcheck:` that calls `/health`, since the README already uses that endpoint for verification at `doco-cd/README.md:32-37`.
2. Decide whether `.env.example` should become actionable. Either add `env_file: .env` and wire `TZ: ${TZ}`, or state that `.env.example` is only a local operator reference and that Compose does not consume it.
3. Add local logging rotation if this service will remain outside generated stacks, because `tools/generate_stacks.py:117-127` only injects defaults for services discovered through `x-stack:`.
4. Keep local file secrets documented as a bootstrap split. Do not force the bootstrap controller into the normal SOPS flow unless the maintainer decides it should be managed like other stack services.

Severity under this model:

- High: none identified from the reviewed files.
- Medium: missing Docker container `healthcheck:` and unclear `.env.example` consumption.
- Low: missing logging rotation, because impact depends on host log policy.

## Decision path 2: expose webhooks through Traefik

If GitHub webhook delivery should use this repository's standard ingress path, the ingress gap becomes high priority. Polling still works without it, but repo-standard webhook exposure needs explicit Compose changes.

Required ingress changes:

1. Attach the service to the Traefik network that matches the deployment model:

   ```yaml
   services:
     doco-cd:
       networks:
         - default

   networks:
     default:
       name: <traefik-network-name>
       external: true
   ```

   Use `traefik-public` when manually attaching Doco-CD to the generated Swarm Traefik stack, matching `AGENTS.md:16`, `stacks/README.md:17-20`, and `stacks/infrastructure.yml:21-24`. Use `traefik` only when running against the source Compose Traefik network, as shown by `website/docker-compose.yml:19-22` and `edge-graphql/docker-compose.yml:26-29`. If Doco-CD becomes stack-managed through `x-stack:`, the source Compose file can follow the `traefik` pattern because `tools/generate_stacks.py:317-323` rewrites the generated stack network to `traefik-public`. Since `doco-cd/` currently has no `x-stack:`, that rewrite will not happen for manual bootstrap.

2. Add Traefik labels following the existing pattern:

   ```yaml
   labels:
     - "traefik.enable=${TRAEFIK_ENABLE}"
     - "traefik.http.routers.doco-cd.rule=Host(`${HOST}`)"
     - "traefik.http.routers.doco-cd.entrypoints=web,websecure"
     - "traefik.http.routers.doco-cd.service=doco-cd"
     - "traefik.http.routers.doco-cd.tls=true"
     - "traefik.http.routers.doco-cd.tls.certresolver=${CERT_RESOLVER}"
     - "traefik.http.services.doco-cd.loadbalancer.server.port=${PORT}"
   ```

   This matches the shape used by `website/docker-compose.yml:9-16`.

3. Wire environment variables with `env_file: .env`, and expand `doco-cd/.env.example` with at least `TRAEFIK_ENABLE`, `CERT_RESOLVER`, `HOST`, and `PORT`, similar to `beszel/.env.example:1-5`.
4. Keep health terminology separate:
   - Docker container `healthcheck:` belongs under the service and is useful for local Compose or Swarm task health.
   - Traefik load balancer healthcheck is a label such as `traefik.http.services.edge-graphql.loadbalancer.healthcheck.path=/health`, shown at `edge-graphql/docker-compose.yml:18`.
5. Revisit the security note at `doco-cd/README.md:69-73`. Exposing `/v1/webhook` through Traefik means the webhook secret and any router middleware choices become part of the ingress decision.

Severity under this model:

- High: no Traefik labels and no shared ingress network for repo-standard webhook exposure.
- Medium: `.env.example` is not consumed and lacks ingress variables, and Docker container health is not declared.
- Low: missing Traefik load balancer healthcheck label, if Docker container health is already added.

## Decision path 3: make Doco-CD stack-managed

If Doco-CD should be generated into `stacks/` and deployed by `stackctl.sh`, this is a separate decision from webhook exposure. The current absence of `x-stack:` and `swarm.fragment.yml` is not an automatic defect while Doco-CD remains a host-level bootstrap controller.

Required stack-management changes:

1. Add an `x-stack:` value to `doco-cd/docker-compose.yml` so `tools/generate_stacks.py:330-354` can discover it.
2. Add `doco-cd/swarm.fragment.yml` for Swarm-only settings such as `deploy`, placement, resources, and any stack-specific network or secret choices, following `AGENTS.md:13-16` and `stacks/README.md:14-21`.
3. Regenerate stacks through `./stackctl.sh generate` or `./stackctl.sh sync`, not by editing `stacks/` directly, per `AGENTS.md:5-9` and `stacks/README.md:1-7`.
4. Account for generator effects. Compose-only keys such as `container_name` and `restart` are stripped, logging defaults are injected, env file and bind paths are rewritten, named volumes are marked external, and the generated stack network is `traefik-public`.
5. Resolve the bootstrap tradeoff before doing this. If Doco-CD is required to deploy or update the same stacks that include it, failure recovery and first-install steps become more coupled. A host-level bootstrap controller is simpler for initial deployment and recovery.

Severity under this model:

- High: no `x-stack:` if the explicit goal is stack-managed Doco-CD.
- Medium: no `swarm.fragment.yml` for Swarm-only scheduling and resource policy.
- Low: generated logging defaults would cover rotation after stack adoption.

## Maintainer decisions needed

1. Should Doco-CD remain polling-only and local-only by default?
2. Should webhook delivery be exposed through Traefik, a tunnel, or not exposed at all?
3. If Traefik exposure is desired, what host name, certificate resolver, and router enable default should be used?
4. Should `.env.example` become an actual Compose input through `env_file: .env`, or remain reference-only documentation?
5. Should Doco-CD stay as a host-level bootstrap controller, or become stack-managed with `x-stack:` and `swarm.fragment.yml`?
6. Should Doco-CD bootstrap secrets remain local Docker secret files, or should they later join the SOPS workflow used by stack services after the bootstrap model is settled?
