---
applyTo: "**"
description: Minimal Copilot shim for Local-Stack; AGENTS.md is canonical.
---

## Local-Stack Copilot Shim

Primary instructions live in [AGENTS.md](../../AGENTS.md). Use that file as the canonical agent guide.

## Critical Guardrails

- Do not edit generated rendered stack outputs.
- Do not use or modify deprecated root-level `swarm.*.yml` files.
- Prefer service-local source changes (`docker-compose*.yml`, `swarm.fragment.yml`, `.env.example`) and then regenerate/sync stacks.
- Keep exposed services on `traefik-public` with correct Traefik labels.
- Keep secrets out of source; use environment variables and follow [docs/Managing Secrets.md](../../docs/Managing%20Secrets.md).

## Canonical References

- [AGENTS.md](../../AGENTS.md)
- [README.md](../../README.md)
- [stacks/README.md](../../stacks/README.md)