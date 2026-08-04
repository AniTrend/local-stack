# Local-Stack Doco-CD Deploy Runner

One-shot deployment runner invoked by Doco-CD. Fetches the repository, runs pre-deployment checks, and deploys Swarm stacks via `stackctl.sh`.

> **Compatibility path note:** this runner intentionally uses `./stackctl.sh`
> (the repository-root compatibility wrapper), not the `stackctl` CLI, because
> the runner's Linux image does not yet have a verified CLI installation.
> The `stackctl` CLI is the preferred interface elsewhere in this repo; revisit
> this runner once the Linux image ships an explicit, verified CLI install
> path. The entrypoint behavior is unchanged in this phase.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_STACK_REPOSITORY` | Required | Git repository URL |
| `LOCAL_STACK_REF` | `dev` | Branch or ref to deploy |
| `LOCAL_STACK_WORKDIR` | `/workspace/local-stack` | Persistent workspace path |
| `LOCAL_STACK_DEPLOY_MODE` | `secrets` | `secrets`, `plain-env`, or `dry-run` |
| `LOCAL_STACK_TARGET_STACKS` | `infrastructure,observability,platform` | Comma-separated stack list |

## Deploy Modes

- **secrets**: SOPS + age decryption, renders `.env`, deploys stacks, removes plaintext `.env` files
- **plain-env**: Uses pre-existing `.env` files directly (no SOPS)
- **dry-run**: Renders and validates stacks without deploying

## Rollback

### Via Git Revert (recommended)

```bash
git revert <bad_merge_commit>
git push origin dev
```

Doco-CD detects the revert and redeploys.

### Manual Host Rollback

```bash
cd /path/to/local-stack
git fetch --prune origin dev
git reset --hard <known_good_commit>
stackctl secrets deploy        # preferred; fallback: ./stackctl.sh secrets deploy
```

## Cautions

- Stateful service updates (postgres, mongo, redis, grafana, prometheus, loki, tempo, portainer, growthbook) may require manual backup and migration steps that the deploy runner cannot automate. Take a backup snapshot before deploying major version bumps to any stateful service.

## Security

- Docker socket (`/var/run/docker.sock`) is mounted into this container. This grants full Docker host access. The runner must be treated as privileged infrastructure.
- SOPS age private key is mounted read-only at `/root/.config/sops/age`.
- The runner uses a file lock (`flock`) to prevent concurrent deployments.
- The runner accepts no arbitrary shell input from Doco-CD or webhook payloads.

## SOPS Key Setup

The runner expects the SOPS age private key at `/opt/local-stack/sops/age/keys.txt` on the Docker host. Create this file with your age identity:

```bash
sudo mkdir -p /opt/local-stack/sops/age
sudo cp /path/to/age-key.txt /opt/local-stack/sops/age/keys.txt
sudo chmod 600 /opt/local-stack/sops/age/keys.txt
```

## Updating the Runner

Changes to `entrypoint.sh` or `Dockerfile` require a manual image rebuild:

```bash
docker compose -f deploy/doco/local-stack-deployer/docker-compose.yml build
```

Doco-CD does not rebuild local images automatically.

## Locking

Concurrent deploys are prevented via `flock` on `/tmp/local-stack-deploy.lock`. If a deployment is already in progress, subsequent invocations exit with code 75 (temporary failure).
