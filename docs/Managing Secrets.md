# Managing Secrets Securely

Never store real secrets in `.env` files in the repo. Keep `.env.example` as documentation with placeholders only.

## Recommended approach (encrypted files committed to git)

Use `sops` + age (or GPG) to encrypt per-environment secrets that can be safely committed.

### 1) Install tools
- age: https://age-encryption.org
- sops: https://github.com/getsops/sops

### 2) Create an age key pair (once)
```bash
# writes to ~/.config/sops/age/keys.txt
age-keygen -o ~/.config/sops/age/keys.txt
```
Add the public recipient from that file (starts with `age1...`) to your repository SOPS config.

### 3) Add a SOPS config
Create `.sops.yaml` at repo root:
```yaml
# Encrypt files matching these globs with the recipient below
creation_rules:
  - path_regex: secrets/.*\.(env|yaml|yml)$
    age: ["AGE1_PUBLIC_KEY_HERE"]
    encrypted_regex: '^(?!#)'
```
Replace `AGE1_PUBLIC_KEY_HERE` with your public age key.

### 4) Create encrypted secret files
Place per-environment secrets under `secrets/` and encrypt with sops:
```bash
mkdir -p secrets
printf "TRAEFIK_ENABLE=true\nSSO_CREDENTIALS=admin:$apr1$...\n" > secrets/traefik.dev.env
sops -e -i secrets/traefik.dev.env
```
The file is now encrypted at rest and safe to commit.

### 5) Decrypt for local use
```bash
# Produces a plaintext file for docker usage (do not commit this)
sops -d secrets/traefik.dev.env > traefik/.env
```
You can add a simple make/script target to automate decrypt -> deploy -> clean.

### 6) CI/CD or remote deploy
On a deployment host, provision the age private key (read-only, secured). Decrypt secrets just-in-time before `docker stack deploy`.

## Using Docker Swarm secrets (optional/advanced)
Docker Swarm supports native secrets. You can combine sops+age with `docker secret create`:

1) Decrypt locally in memory and pipe to secret create:
```bash
sops -d secrets/traefik.dev.env | docker secret create traefik_env -
```
2) Reference the secret in your stack file using `secrets:` and `env_file` alternatives where appropriate.

This is more granular and keeps values out of env vars in the container filesystem, but requires adjusting service configs to read from files or environment sourced from secrets.

## Git hygiene
- Commit only `.env.example` files and encrypted files under `secrets/`.
- Never commit plaintext `.env`.
- Add a `.gitignore` rule for `**/.env` and `**/*.env.decrypted` as needed.

## Troubleshooting
- If `sops` can’t decrypt: ensure the age private key is in `~/.config/sops/age/keys.txt`.
- For team usage: include multiple recipients in `.sops.yaml` so each developer can decrypt.
