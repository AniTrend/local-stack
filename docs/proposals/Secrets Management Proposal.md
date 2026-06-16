# Secrets Management Proposal (Docker Swarm + Portainer)

Target: Infra
Status: Proposal
Date: 2025-09-20

## Summary
Move sensitive configuration out of committed `.env` files and labels. Adopt an encrypted-at-rest workflow for secrets with just-in-time decryption at deploy time. Prefer Docker Swarm secrets for services that support `*_FILE` environment variables.

Recommended: Option A (SOPS + age + Docker Swarm secrets). Portainer can still be used to manage and observe secrets without changing the core flow.

## Options

### Option A — SOPS + age (git) → Docker Swarm secrets (recommended)
Encrypted source of truth committed to git. Decrypt on the Swarm manager at deploy time and create Docker secrets. Services read secrets from `/run/secrets` via `*_FILE` envs.

Pros:
- Native to Docker Swarm; least moving parts.
- Encrypted at rest in git; safe to PR/review.
- Works with both CLI and Portainer (Portainer shows secrets).

Cons:
- Images must support file-based envs (e.g., `POSTGRES_PASSWORD_FILE`). Some apps may require adaptation.
- Traefik labels cannot reference secrets directly—use mounted files/config or inject at deploy time.

Concrete steps:
1) Keep only placeholders in `.env.example`. Do not commit real `.env`.
2) Store real values in encrypted files under `secrets/` (SOPS + age). See `docs/secrets.md`.
3) At deploy time, decrypt just-in-time and create Docker secrets, e.g.:
   - `sops -d secrets/postgres.dev.env | grep POSTGRES_PASSWORD= | cut -d= -f2 | docker secret create postgres_password -`
4) Reference secrets in stacks:
```yaml
services:
  postgres:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
    secrets:
      - postgres_password
secrets:
  postgres_password:
    external: true
```
5) For values used in Traefik labels (cannot be secrets), prefer mounted files (e.g., `htpasswd`), or decrypt a minimal env file just before deploy (never commit it).

Migration impact:
- Update stack files to use secrets where supported (DBs, certain apps).
- Add a small deploy script to read encrypted files, create secrets, and deploy stacks.

---

### Option B — SOPS + age → Portainer API (Portainer-managed secrets)
Same encrypted source of truth. Instead of `docker secret create`, use Portainer’s API to create/update secrets for your endpoint. Stacks reference secrets exactly as in Option A.

Pros:
- Centralized via Portainer; admins can manage and audit via UI.
- Fits teams who use Portainer to operate Swarm.

Cons:
- Requires Portainer API token and scripting against API endpoints.
- Same constraints: labels can’t pull from secrets; some images may need `*_FILE`.

Concrete steps:
1) Generate Portainer API key (Settings → API Keys).
2) Write a small script to:
   - `sops -d secrets/<svc>.env |` extract values → POST to `/api/endpoints/{id}/docker/secrets/create`.
   - Trigger stack redeploy via Portainer Stack API (optional) or `docker stack deploy` locally.
3) Reference secrets in stacks as in Option A.

Migration impact:
- Same as Option A plus a Portainer API wrapper.

---

### Option C — Portainer GitOps + Environment overrides
Portainer pulls the repo and deploys stacks. Secrets/vars are provided via Portainer UI or variables file injected at deploy time.

Pros:
- Simple for operators living in Portainer UI.

Cons:
- Still need a secure path to get real values into Portainer; avoid storing plaintext in repo.
- Less automation-friendly than A/B for CLI-centric workflows.

---

## Recommended plan (Option A)

Phase 1: Foundation ✅
- Keep `.env.example` placeholders. ✅ Done.
- Add `.sops.yaml` and `docs/Managing Secrets.md`. ✅ Done — now uses service-local `.env.enc` pattern with `stackctl.sh secrets`.
- Create age key(s) and commit encrypted files per service directory (team recipients in `.sops.yaml`). ✅ Done — see `stackctl.sh secrets encrypt`.

Phase 2: Convert priority services
- Databases: switch to `*_FILE` and define `secrets:` in `stacks/infrastructure.yml`.
- GrowthBook/Apps: evaluate `*_FILE` support; where unsupported, prefer mounted files or just-in-time decrypted `env_file` (not committed).
- Traefik auth: keep htpasswd as a mounted file (already done); avoid secrets in labels.

Phase 3: Automate deploy
- Add a deploy script/Make target:
  - Decrypt necessary files via sops.
  - Create/rotate Docker secrets.
  - `docker stack deploy` the stacks.
  - Clean up any plaintext artifacts.

Phase 4: (Optional) Portainer integration
- Instead of `docker secret create`, use Portainer API to create/rotate secrets.
- Optionally have Portainer pull stacks from git and trigger redeploys via API.

## Open questions
- Which services require secrets and support `*_FILE`? (Postgres yes; Redis no; Mongo users might need env vars or runtime files.)
- Who holds the age private key for CI/CD? (One or more maintainers; store on deployment hosts only.)
- Rotation cadence? (Document per-service rotation procedure in `docs/secrets.md`.)

## Appendix: Example secret extraction
Extract a single key from an encrypted env file without writing plaintext to disk:
```bash
# Create postgres password secret from an encrypted env file
sops -d secrets/postgres.dev.env \
  | awk -F= '/^POSTGRES_PASSWORD=/{print $2}' \
  | docker secret create postgres_password -
```
