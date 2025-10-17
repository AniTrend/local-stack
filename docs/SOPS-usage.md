# SOPS Usage Guide (local development)

This repository supports using SOPS to keep secrets encrypted in the repository while allowing local
developers to decrypt them during setup.

High level
- Keep only encrypted files in the repository (e.g. `.env.enc.yaml`).
- Use `.sops.yaml` (copy from `.sops.yaml.example`) to configure encryption backends (age/KMS/PGP).
- Locally, decrypt with the `sops` CLI and write to `.env` when needed.

Examples

1) Decrypt for local use

```bash
# requires sops installed and the proper keys available in your keystore
./stackctl.sh secrets decrypt --in apisix/api-gateway/.env.example.enc.yaml --out apisix/api-gateway/.env --force
```

2) Encrypt a plaintext .env into an encrypted file

```bash
# Use sops to encrypt; this will respect .sops.yaml
./stackctl.sh secrets encrypt --in apisix/api-gateway/.env --out apisix/api-gateway/.env.enc.yaml
```

3) Best practices
- Never commit plaintext `.env` files. Add `.env` to your global or repo `.gitignore`.
- Add `.sops.yaml` to your local environment (do not commit a production `.sops.yaml` with real keys).
- Rotate keys and update `.sops.yaml` as needed.

Security notes
- The `stackctl_cli` helpers never print secret values; decrypt writes to a file.
- For CI, configure a decrypt step using appropriate secret storage (KMS/PGP) and avoid storing keys in the repo.
