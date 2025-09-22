---
applyTo: './tools/**'
description: Guardrails and expectations for Python utilities under ./tools (renderers, helpers).
---

# ./tools Instructions

This document defines context and safeguards for Python utilities in `./tools`, including the compose renderer.

## Scope & Purpose
- Utilities in `./tools` support local development and deployment ergonomics (e.g., rendering compose files).
- They should remain dependency-light and safe-by-default.

## Safety & Secrets
1. Never hardcode or print secret values. Use placeholders or summarize paths.
2. Do not read `.env` files outside intended scope. Respect per-service `env_file` paths.
3. Avoid writing back into source compose files; write outputs into a dedicated directory (configured by caller or adjacent to source) and ensure repo `.gitignore` excludes them.

## Coding Standards
- Python 3.8+ compatible, prefer stdlib where possible.
- Use `PyYAML` for YAML parsing; pin via `tools/requirements.txt`.
- Keep modules self-contained and avoid network calls.

## Interpolation renderer (render_compose.py) contract
- Inputs: `-i/--input` path to compose YAML, `-o/--output` destination path, optional `--strict`.
- Behavior:
  - Load per-service `env_file`(s), then merge with `environment` and the current process env (in that precedence order: env -> env_file -> environment overrides).
  - Perform recursive string interpolation supporting `${VAR}`, `${VAR-default}`, `${VAR:-default}`, plus unbraced `$VAR`.
  - Leave unresolved placeholders intact unless `--strict` is set (then fail non-zero).
- Outputs: Write a rendered YAML preserving structure; do not modify file permissions of source.

## Validation
Before adopting changes to any `./tools` utility:
- Syntax check: `python3 -m py_compile <file.py>` should pass.
- Minimal run: execute with `--help` and one representative happy path to ensure no runtime import errors.
- For the renderer, validate a sample file with `docker compose -f <rendered> config`.

## Error Handling & UX
- Print clear, actionable errors to stderr and exit non-zero on fatal issues.
- Warning instead of crashing for missing env files; proceed with best-effort rendering.
- Avoid verbose dumps; prefer concise summaries and paths.

## Dependencies
- Manage dependencies in `tools/requirements.txt`. Prefer narrow, pinned ranges.
- Do not introduce heavyweight frameworks.

## Tests & Docs
- Keep `tools/README.md` accurate with basic install and usage steps.
- If behavior changes (flags, precedence, patterns), update docs alongside code.

## Security & Compliance
- Never check rendered files into VCS. Ensure `.rendered/` or caller-provided output directories are ignored.
- Follow the repository’s secrets-preservation guidance for logging and examples.
