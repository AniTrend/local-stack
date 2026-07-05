# Doco-CD Bootstrap Stack

Host-level bootstrap for the Doco-CD deployment controller. Deploy this manually before any automated deployments.

## Prerequisites

- Docker Swarm initialized (`docker swarm init`)
- Docker socket accessible

## Bootstrap

1. Create secrets directory and generate secrets:

   ```bash
   mkdir -p doco-cd/secrets
   openssl rand -hex 32 > doco-cd/secrets/webhook_secret
   openssl rand -hex 32 > doco-cd/secrets/api_secret
   ```

2. Deploy Doco-CD:

   ```bash
   docker compose -f doco-cd/docker-compose.yml up -d
   ```

   Or in Swarm:

   ```bash
   docker stack deploy -c doco-cd/docker-compose.yml doco-cd
   ```

3. Verify:

   ```bash
   docker logs doco-cd
   curl http://127.0.0.1:8088/health
   ```

## Trigger Modes

### Polling (default, recommended)

Doco-CD polls the repository on an interval (configured via `POLL_CONFIG`). When a new commit is detected on `dev`, it triggers the deployment.

- Interval: 300 seconds (5 minutes)
- Reference: `refs/heads/dev`
- No inbound endpoint required

### Webhook

For event-driven deploys, configure a GitHub webhook pointing to `https://<host>:8088/v1/webhook`.

- Secret: `doco-cd/secrets/webhook_secret` (must match the GitHub webhook secret)
- Content type: `application/json`
- Events: `push` only
- Webhook filter: only `refs/heads/dev` is accepted (configured in `.doco-cd.yml`)

### Switching Between Modes

Both polling and webhook can run simultaneously. Use `run_once: true` in the poll config to seed the initial clone, then rely on webhooks for subsequent deploys.

## Secrets

Secrets are passed as files via Docker secrets:

- `WEBHOOK_SECRET_FILE: /run/secrets/doco_webhook_secret`
- `API_SECRET_FILE: /run/secrets/doco_api_secret`

## Important Security Notes

- Docker socket access grants full host control. Keep Doco-CD's webhook endpoint restricted to `127.0.0.1` unless using a tunnel or authenticated reverse proxy.
- The API is disabled by default unless `API_SECRET` is set.
- The `/v1/webhook` endpoint validates signatures using the webhook secret.

## Exposure Model

Doco-CD binds to `127.0.0.1:8088` by default, accepting only local connections. For external webhook delivery:

1. Use a reverse proxy (Traefik, nginx) with TLS in front of Doco-CD.
2. Or use a tunnel (Cloudflare Tunnel, ngrok) with endpoint filtering.
3. Or rely on polling mode exclusively (no inbound port needed).
