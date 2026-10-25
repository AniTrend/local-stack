# Local Docker platform lab

This is the P1 disposable Docker lab for testing the Pulumi Docker program on a local Linux or macOS Docker engine. It does not provision cloud resources, initialize Swarm, modify service Compose files, or claim production readiness.

## Host setup

Use a per-user version manager to activate the pins from `.node-version` and `.python-version`; do not change machine-wide defaults. The Makefile prefers `.venv-platform/bin`, `.tools/platform/node/bin`, and `.tools/platform/bin` when present; otherwise it uses tools from `PATH`.

From the repository root, create the Python environment and install the locked dependencies:

```sh
python3.14 -m venv .venv-platform
.venv-platform/bin/python -m pip install --require-hashes -r tools/platform/requirements.lock
export PLATFORM_ANSIBLE_COLLECTIONS_PATH=.tools/platform/collections
export ANSIBLE_COLLECTIONS_PATH="$PLATFORM_ANSIBLE_COLLECTIONS_PATH"
ansible-galaxy collection install -p "$PLATFORM_ANSIBLE_COLLECTIONS_PATH" -r ansible/requirements.yml
npm exec --yes --package=node@24.22.1 --package=npm@11.19.1 -- npm ci --prefix infra/pulumi/docker
```

`ansible-galaxy` installs the pinned collections into the ignored project-local `.tools/platform/collections`; the Makefile sets Ansible's collection search path there, and `platform-doctor` fails if any pinned collection is missing or mismatched. The `npm exec` command uses the exact Node and npm versions from the pins without changing machine-wide defaults. Run the Make targets below from a shell with those versions on `PATH`, or prepend the same `npm exec` package prefix to each `make` command.

Install Pulumi CLI `3.272.0` in `.tools/platform/bin/pulumi`, or set `PLATFORM_PULUMI_BIN` to an existing pinned executable. Pulumi release assets and their GitHub-published SHA-256 digests:

| Host | Asset | SHA-256 |
|---|---|---|
| Linux x86_64 | `pulumi-v3.272.0-linux-x64.tar.gz` | `58d545f2b98761051922008ebd381ecef95484d7f7a5ff7faa15d7a780ea84f6` |
| Linux arm64 | `pulumi-v3.272.0-linux-arm64.tar.gz` | `4f0741901b8982c4326b702dabf483c63d2cf77c88ac42dd752b72541284a534` |
| macOS x86_64 | `pulumi-v3.272.0-darwin-x64.tar.gz` | `2c11154168e4dc58d43c2b70b0941fa3335d911af2806feac7bf3b8072a5f09a` |
| macOS arm64 | `pulumi-v3.272.0-darwin-arm64.tar.gz` | `1fb554bf39ad83ba6eef6ecb7ac5a14b8158941ccd97d201837d13dc09806014` |

Download the host-matched asset from the `pulumi/pulumi` GitHub release `v3.272.0` and verify its digest before extraction. The Makefile prefers `.venv-platform/bin`, `.tools/platform/node/bin`, and `.tools/platform/bin` when present; otherwise it uses tools from `PATH`.

## Select a local daemon

Select and explicitly allowlist the same Docker context. Replace `default` with a locally inspected context name; never copy a production or remote context into this allowlist.

```sh
export PLATFORM_DOCKER_CONTEXT=default
export PLATFORM_ALLOWED_DOCKER_CONTEXTS=default
```

`platform-doctor` is read-only. It rejects remote endpoints, production-like context names, cloud credentials, active or unknown Swarm state, unsupported host/daemon architectures, insufficient CPU/memory/disk, and mismatched pinned tools. It reports host and daemon architecture separately and selects the fixture platform from the daemon architecture.

## Run the lab

Use this one lifecycle from the repository root:

```sh
make platform-doctor ENV=lab
make platform-lab-up ENV=lab
make platform-lab-test ENV=lab
make platform-lab-down ENV=lab
```

`platform-lab-up` generates a UTC run ID, a temporary SSH keypair, a passphrase-protected local Pulumi stack, and uniquely labelled resources. It previews and applies the stack; a container healthcheck waits for the SSH listener before the command returns. `platform-lab-test` requires the second identical update to report no changes, inspects actual Docker state, verifies loopback-only SSH access and `uname -s`, changes the resource revision label, and verifies the controlled update. `platform-lab-down` verifies the Pulumi resource inventory and Docker ownership labels before destroying the active stack, then verifies removal. It never invokes Docker prune or removes unrelated resources.

Only one lifecycle operation per checkout runs at a time. The run ID and stack name are printed by `up`; `test` and `down` use the active run record. If a process is interrupted, rerun `make platform-lab-up ENV=lab` to reconcile the active stack, or `make platform-lab-down ENV=lab` to clean it.

This local lab tests only the Docker Pulumi provider and the disposable SSH fixture. It requires the pinned toolchain and an explicitly allowlisted local Docker daemon. It does not provision HCloud resources or prove VM, rehearsal, or production readiness.

The lab uses a separate user-defined bridge, one scratch volume, and a disposable LinuxServer OpenSSH container. The container is capped at 512 MiB of memory and 1 GiB total memory plus swap. The host SSH port is selected from the local ephemeral range and bound to `127.0.0.1`; no host filesystem bind mount is used. The bridge is separate from existing application networks, but it permits outbound traffic. An internal Docker network prevented the host-published SSH port from being reachable on the validated Linux engine. Do not put credentials or production data in this fixture.

The image is pinned by digest and selected for `linux/amd64` or `linux/arm64`. The report records `native` or `emulated` relative to the host and Docker daemon architectures. The image uses `keepLocally: true`, so teardown intentionally retains the content-addressed image cache; it does not prune images.

## Local evidence and separate tiers

The sanitized run manifest is retained at `.artifacts/platform/lab/<run-id>/manifest.json`. It records the source commit and worktree cleanliness, tool versions, host/daemon/image architecture, digest, resource names, no-op/update/SSH results, and cleanup status. It excludes the local Docker socket path, passphrase, and SSH private key. Successful teardown removes the private key, passphrase, local backend, and active-run pointer; the manifest remains ignored by Git.

`infra/pulumi/shared/platform-lab.schema.json` defines the lab output and run-manifest schemas. The CLI validates Pulumi outputs and each manifest write against this contract.

PR CI runs offline doctor fixtures and Pulumi mock tests and uploads their non-secret reports. Those tests are separate from this actual Docker T1 run. The full Linux VM tier for systemd, host networking, and Dokploy is separate; this local lab does not mark VM or production gates passed.
