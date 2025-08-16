# Pulumi Orchestration for Local-Stack

This Pulumi project orchestrates your Docker Compose and Docker Swarm deployments from code, so you can manage everything with `pulumi preview/up/destroy` without relying on separate swarm YAML files.

## Prerequisites
- Node.js 18+
- Pulumi CLI installed and logged in (`pulumi login`)
- Docker Desktop or Docker Engine running

## Install deps

```
cd infra/pulumi
npm install
```

## Choose a stack and set config

We include a `dev` config suggestion in `stacks/dev.yaml`. You can import it:

```
cd infra/pulumi
pulumi stack init dev --non-interactive || true
pulumi stack select dev
pulumi config refresh --force
# Optionally set mode to swarm
# pulumi config set local-stack:mode swarm
```

## Deploy (Compose mode)

```
npm run up
```

This will:
- Ensure the external `traefik` docker network exists
- Run docker compose up -d for all configured groups (postgres, redis, mongo, traefik, apisix*, observability, etc.)

Note: Ensure each service directory has its `.env` present if its compose references `env_file: .env` (copy from `.env.example` where provided).

## Deploy (Swarm mode, no YAML)

```
pulumi config set local-stack:mode swarm
npm run up
```

This will:
- Ensure swarm is initialized
- Create overlay networks/volumes and Docker services directly via Pulumi command resources (no stack YAML files)

## Destroy

```
npm run destroy
```

- Compose mode: runs docker compose down for each group
- Swarm mode: removes the stacks via `docker stack rm`

## Notes
- This approach keeps your current compose files as the source of truth. We can incrementally migrate specific services to native Pulumi Docker resources later if desired.
- Update the service list in `stacks/dev.yaml` to control which groups are managed.
