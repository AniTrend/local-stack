# Compose Renderer

This tool renders Docker Compose/Stack YAML files by interpolating `${VAR}` references using per-service `env_file` and `environment` values.

Why: `docker stack deploy` only interpolates variables from the shell environment or a root `.env` file. It does not load variables from service-level `env_file` for interpolation (e.g., in labels/command/healthcheck). This renderer bridges that gap.

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r tools/requirements.txt
```

## Usage

```sh
# Render a stack file; output keeps docker-compose.* prefix under .rendered/
python3 tools/render_compose.py -i stacks/infrastructure.yml -o .rendered/docker-compose.infrastructure.rendered.yml
```

Then use the rendered file for validation or deployment:

```sh
docker compose -f .rendered/docker-compose.infrastructure.rendered.yml config
# or
docker stack deploy -c .rendered/docker-compose.infrastructure.rendered.yml infrastructure
```

## Behavior

- Interpolates strings recursively across the YAML document.
- Supports `${VAR}`, `${VAR-default}` (default when unset), and `${VAR:-default}` (default when unset or empty).
- Variable precedence per service:
  1. Current shell environment
  2. Values from service `env_file` (one or many)
  3. Values from service `environment`
- Leaves unresolved variables as-is by default. Use `--strict` to error if any remain.

## Limitations

- This is a preprocessing step; paths remain relative to the original file location.
- It does not evaluate command substitutions or complex expressions, only variable substitution.

## Platform infrastructure helpers

`tools/platform/lab.py` owns the disposable local Docker Pulumi lifecycle. `tools/platform/pulumi_preview.py` previews the active local lab or an already configured HCloud stack without applying changes. `make platform-pulumi-test ENV=lab` runs Docker and HCloud Pulumi mocks plus platform Python tests. See [the local lab runbook](../docs/platform/local-lab.md) and [HCloud provisioning contract](../docs/platform/pulumi-hcloud.md).

`tools/platform/ansible_inventory.py` validates the HCloud inventory v1 or the versioned external lab-VM inventory together with a signed SSH host-trust record. It writes a sanitized static Ansible inventory and mode-0600 `known_hosts` file under a new ignored `.artifacts/platform/<run-id>` directory; it does not connect to or mutate the host. The lab-VM inventory describes an externally provided native VM and does not provision one.

Run `python3 tools/platform/ansible_inventory.py --inventory FILE --trust-bundle FILE --trust-root PEM --environment lab|rehearsal|production --output-dir .artifacts/platform/RUN_ID/ansible` to validate the versioned inventory and signed trust record. `--trust-root` must be an Ed25519 public key from an approved source independent of the bundle. SSH host checking is forced on, user/system SSH configuration and `KnownHostsCommand` are disabled, `%` path tokens are escaped, and `$` path expansion is rejected. The output directory must be new.

`tools/platform/ansible_runner.py` implements the required `make platform-ansible-test ENV=lab` and `make platform-host-verify ENV=lab TIER=vm` interfaces. The Docker target requires `PLATFORM_DOCKER_CONTEXT` and `PLATFORM_ALLOWED_DOCKER_CONTEXTS`, validates a local non-Swarm endpoint, builds a digest-pinned Ubuntu 24.04 fixture with host networking for build-time package access only, then runs Molecule syntax, convergence, idempotence, drift correction and verification. The running fixture uses the default isolated Docker bridge and publishes no ports.

The full VM target requires `PLATFORM_VM_INVENTORY`, `PLATFORM_VM_TRUST_BUNDLE`, `PLATFORM_VM_TRUST_ROOT`, `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY`, `PLATFORM_VM_AUTOMATION_PUBLIC_KEY`, `PLATFORM_VM_AUTOMATION_PRIVATE_KEY`, `PLATFORM_TAILSCALE_AUTH_KEY` and `PLATFORM_TAILSCALE_TAG`. The trust root must come from an approved source independent of the signed host-trust bundle. If the inventory declares create-only formatting, also set `PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT=I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES`. The runner verifies the automation user's SSH reconnect before firewall changes, runs storage-safety and reboot checks, requires a zero-change second converge, writes a non-secret `manifest.json` under `.artifacts/platform/<run-id>/`, and removes the generated inventory and `known_hosts` afterward. It does not provision cloud resources; absent VM inputs produce a blocked result.
