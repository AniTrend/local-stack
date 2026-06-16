# Managing Secrets Securely

Secrets are encrypted at rest in git using SOPS + age and decrypted just-in-time at deploy time. Each service directory stores an encrypted `.env.enc` alongside its `.env.example`.

## Workflow Overview

```
.env.example  →  .env (fill values)  →  .env.enc (encrypt)  →  git commit
                                                          ↓
.git (encrypted)  →  .env.enc  →  .env (decrypt)  →  deploy  →  shred .env
```

## Setup

### 1. Install tools

```bash
# macOS
brew install sops age

# Linux
# sops: https://github.com/getsops/sops/releases
# age: https://github.com/FiloSottile/age/releases
```

### 2. Generate an age key pair (once per machine)

```bash
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# The public key is printed — add it to .sops.yaml key_groups
```

### 3. Add your public key to `.sops.yaml`

Edit `.sops.yaml` and add your age public key to the `key_groups` list. Multiple recipients can be listed for team access:

```yaml
creation_rules:
  - path_regex: \.env$
    key_groups:
      - age:
          - age1existingkey...   # existing recipient
          - age1yournewkey...    # your new key
```

## Encrypting secrets

For a single service:

```bash
# Create .env from .env.example and fill in real values
cp postgres/.env.example postgres/.env
# Edit postgres/.env with real values...

# Encrypt
./stackctl.sh secrets encrypt postgres
```

For all services at once:

```bash
./stackctl.sh secrets encrypt
```

This runs `sops --encrypt --input-type dotenv --output-type dotenv .env > .env.enc` for each service directory that has a `.env` file.

## Deploying

Deploy decrypts, renders, deploys, and shreds in one step:

```bash
# Deploy a specific service's stack
./stackctl.sh secrets deploy postgres

# Deploy all services
./stackctl.sh secrets deploy
```

The deploy operation:
1. Decrypts `.env.enc` → `.env` for each target service
2. Regenerates rendered stack files (variable substitution)
3. Deploys the relevant Docker Swarm stacks
4. Shreds all plaintext `.env` files

## Decrypting (manual)

If you need to inspect or edit secrets without deploying:

```bash
# Decrypt a single service
./stackctl.sh secrets decrypt postgres

# Decrypt all services
./stackctl.sh secrets decrypt
```

**Remember to clean up plaintext files after editing:**

```bash
./stackctl.sh secrets clean
```

## Cleaning up

Remove all plaintext `.env` files that have a corresponding `.env.enc`:

```bash
./stackctl.sh secrets clean
```

This uses `shred -u` when available, falling back to `rm -f` on systems without `shred`.

## Key rotation

After adding a new recipient to `.sops.yaml`:

```bash
sops updatekeys --yes **/.env.enc
```

## Re-encrypting after editing

```bash
# Decrypt, edit, re-encrypt
./stackctl.sh secrets decrypt postgres
# Edit postgres/.env...
./stackctl.sh secrets encrypt postgres
./stackctl.sh secrets clean
```

## Git hygiene

- **Commit**: `.env.example` (placeholders) and `.env.enc` (encrypted secrets)
- **Never commit**: `.env` (plaintext, gitignored)
- The `.gitignore` rule `!*.env.enc` ensures encrypted files are tracked

## Troubleshooting

- **`sops` can't decrypt**: Ensure the age private key is at `~/.config/sops/age/keys.txt` and the corresponding public key is in `.sops.yaml`.
- **`shred` not found**: The script falls back to `rm -f`. Install `shred` (part of `coreutils` on Linux) for secure deletion.
- **`sops` or `age` not found**: Run `./stackctl.sh doctor` to check prerequisites, or install them manually.
