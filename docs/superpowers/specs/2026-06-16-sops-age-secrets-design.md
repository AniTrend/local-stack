# SOPS + age Secrets Management Setup

Date: 2026-06-16
Status: Approved
Branch: chore/sops-age-secrets-setup

## Context

Local-Stack currently uses plaintext `.env` files per service, with `.env.example` as documentation. The existing `.sops.yaml` targets a `secrets/` directory that was never adopted, and `docs/Managing Secrets.md` describes a workflow that doesn't match the repo's actual tooling. The homelab repo at `../../docker/` has a working SOPS+age pattern using service-local `.env.enc` files with a `deploy.sh` that decrypts, deploys, and shreds.

Goal: adopt the same service-local `.env.enc` pattern in local-stack, integrated with `stackctl.sh`, so secrets are encrypted at rest in git and decrypted just-in-time at deploy.

## Architecture

Each service folder (e.g., `postgres/`, `traefik/`, `redis/`) keeps a committed `.env.enc` — the SOPS-encrypted version of its `.env`. Plaintext `.env` is decrypted just-in-time by `stackctl.sh secrets deploy`, used for rendering and stack deployment, then shredded. Generated Swarm stacks continue referencing service-local `.env` via `env_file` — no stack file changes needed.

```
postgres/
  .env.example      # placeholders (committed)
  .env.enc          # encrypted secrets (committed)
  .env              # plaintext (gitignored, created by decrypt)
  docker-compose.yml
  swarm.fragment.yml
```

## File Changes

### `.sops.yaml`

Replace the current `secrets/`-targeted config with a service-local `.env` pattern matching `../../docker`:

```yaml
creation_rules:
  - path_regex: \.env$
    key_groups:
      - age:
          - <AGE_PUBLIC_KEY>
    encrypted_regex: '^(?!#)'
```

- `path_regex: \.env$` matches any `.env` file in any directory.
- `encrypted_regex: '^(?!#)'` skips comment lines during encryption (safe for dotenv).
- The age public key placeholder will be replaced at setup time.

### `.gitignore`

Add an allowlist rule so `.env.enc` files are committed while `.env` stays ignored:

```gitignore
.env
.env.bak*
!*.env.enc
```

The `!*.env.enc` negation pattern ensures encrypted files are tracked even though `.env` is ignored.

### `stackctl.sh`

Add a `secrets` subcommand with four operations:

```
stackctl.sh secrets encrypt [service]   # sops -e -i service/.env → service/.env.enc
stackctl.sh secrets decrypt [service]   # sops -d service/.env.enc → service/.env
stackctl.sh secrets deploy [service]    # decrypt → render → stack deploy → shred
stackctl.sh secrets clean               # shred all plaintext .env files
```

- `[service]` is optional; omit to operate on all services that have `.env.enc`.
- `encrypt`: runs `sops --encrypt --input-type dotenv --output-type dotenv service/.env > service/.env.enc`, reading plaintext `.env` and writing `.env.enc` without modifying the original. Requires `sops` and `age` on PATH.
- `decrypt`: runs `sops --decrypt --input-type dotenv --output-type dotenv` from `.env.enc` to `.env`.
- `deploy`: chains decrypt → `render_stack_file` → `docker stack deploy` → `shred -u` on `.env`. Reuses existing `discover_env_example_dirs` to find service folders.
- `clean`: finds all `.env` files that have a corresponding `.env.enc` and shreds them.
- Prerequisite checks: `sops` and `age` must be on PATH; warn if missing.

### `docs/Managing Secrets.md`

Rewrite to document the service-local `.env.enc` workflow:

1. Install `sops` and `age`.
2. Generate an age key pair: `age-keygen -o ~/.config/sops/age/keys.txt`.
3. Add the public key to `.sops.yaml`.
4. Create `.env` from `.env.example`, fill in real values, then `stackctl.sh secrets encrypt <service>`.
5. Deploy with `stackctl.sh secrets deploy [service]`.
6. Clean up plaintext with `stackctl.sh secrets clean`.
7. Key rotation: `sops updatekeys --yes **/.env.enc` after adding a new recipient to `.sops.yaml`.

### `README.md`

Update the secrets/setup section to reference `stackctl.sh secrets deploy` instead of the legacy `cp .env.example .env` + `docker-compose up` flow. Keep the legacy instructions as a fallback for non-Swarm local development.

### `docs/proposals/Secrets Management Proposal.md`

Update Phase 1 status to reflect completion. No structural changes to the proposal — Phase 2 (Docker Swarm native secrets) and Phase 3 (Portainer integration) remain as future work.

## What Stays the Same

- Generated `stacks/*.yml` — untouched, already reference service-local `.env` via `env_file`.
- `.env.example` files — remain as documentation with placeholder values.
- `stackctl.sh env` — still works for listing/recreating `.env` from examples.
- `stackctl.sh doctor` — still warns about missing `.env`.
- `stackctl.sh up` — continues to work with plaintext `.env` for local development.

## Key Management

| Item | Location | Committed? |
|---|---|---|
| Age public key | `.sops.yaml` | Yes |
| Age private key | `~/.config/sops/age/keys.txt` | Never |
| Encrypted secrets | `**/.env.enc` | Yes |
| Plaintext secrets | `**/.env` | No (gitignored) |

Recovery: if the server dies, you need both the `.env.enc` files (in git) and the age private key (backed up to a password manager and offline drive).

## Phase 2 (Future, Not This PR)

Docker Swarm native secrets (`*_FILE` env vars, `docker secret create`) as a later hardening step per the existing proposal. This would require per-service compose changes and is out of scope for this setup.