# Live inventory (P0) and host acceptance (P1) runbook

Covers operational work for issues [#653](https://github.com/AniTrend/local-stack/issues/653) (P0-01), [#654](https://github.com/AniTrend/local-stack/issues/654) (P1-01), [#655](https://github.com/AniTrend/local-stack/issues/655) (P1-02), and [#656](https://github.com/AniTrend/local-stack/issues/656) (P1-03). Start from [workstation.md](workstation.md) (tools, Docker, pinned toolchain, local lab). Contracts: [validation.md](../validation.md), [current-state.md](../current-state.md), [migration-runbook.md](../migration-runbook.md), [ADR 0001](../adr-0001-platform-ownership.md). Next stages: [delivery.md](delivery.md) and [migration.md](migration.md).

Authorization boundary: this runbook authorizes read-only observation of the live host, disposable local lab resources, and one disposable VM you own. It authorizes no cloud spend, no production mutation, no HCloud apply, and no destructive action. Where a required input is missing, the work is blocked and recorded as blocked; blocked is never a pass.

Every command below is labelled with where it runs and what it mutates.

## Implementation status (verify before working)

Checked 2026-10-27 against GitHub and this branch. The repaired P0 PR #673 head is `eb48f84`; compare the full current PR head before working.

| Work item | Status | Where |
|---|---|---|
| #654 P1-01 lab | Implemented, PR [#669](https://github.com/AniTrend/local-stack/pull/669) open (head `feat/platform-lab-654`) | `tools/platform/lab.py`, `infra/pulumi/docker/`, Make targets `platform-doctor`, `platform-lab-up`, `platform-lab-test`, `platform-lab-down`, `platform-preview ENV=lab` |
| #655 P1-02 HCloud program | Implemented, PR [#670](https://github.com/AniTrend/local-stack/pull/670) open (head `feat/platform-hcloud-655`, stacked on #669) | `infra/pulumi/hcloud/`, `tools/platform/pulumi_preview.py`, Make targets `platform-pulumi-test`, `platform-preview ENV=rehearsal|production` |
| #656 P1-03 host baseline | Implemented in open stacked PR [#671](https://github.com/AniTrend/local-stack/pull/671), branch `feat/platform-ansible-656`; earlier unchanged host/container evidence is recorded at `11535ba`, with evidence tooling and this handoff delivered afterward. Full VM acceptance has NOT run | `ansible/`, `tools/platform/ansible_runner.py`, `ansible_inventory.py`, `host_firewall.py`; `platform-ansible-test` and `platform-host-verify` |
| Evidence record validator (parent scope) | Implemented: `tools/platform/evidence.py` behind `make platform-evidence-validate ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_40_HEX_SHA`. Validates completed `lab-run.v1` (TIER=docker) or `host-verify.v1` (TIER=vm) records against their schemas, identity binding, required passing assertions, zero-change counts, cleanup, and recognizable secret markers; exit 2 for nonpassing, incomplete, mismatched, or unknown later schemas. Prints `scope=docker-lab-lifecycle` or `scope=host-baseline` and, by design, never a G0 to G6 gate approval, authenticity claim, or current-runtime statement | `Makefile`, `tools/platform/evidence.py`, `infra/pulumi/shared/host-verify-evidence.schema.json` |
| #653 P0-01 inventory | Implemented in open draft [PR #673](https://github.com/AniTrend/local-stack/pull/673), branch `docs/platform-inventory-653`, repaired head `eb48f84` on 2026-10-27. It is not merged or integrated here: P0 Make targets still fail closed in this P1 checkout, and G0 is NOT complete | Portable PR source paths below; obtain and verify its reviewed head per A1.1 |

Do not treat an open PR, a merged doc PR, or this runbook as runtime proof. Acceptance requires the evidence in the final section.

## Part A: P0-01 live inventory reconciliation (#653)

Goal: replace repository evidence with observed runtime facts, read-only, without changing the live host. The contract is [#653](https://github.com/AniTrend/local-stack/issues/653) and [current-state.md](../current-state.md#live-inventory-output).

### A1. Current state of the tooling

The P0 collector is published in draft [PR #673](https://github.com/AniTrend/local-stack/pull/673), branch `docs/platform-inventory-653`, with review repairs at `eb48f84bb584b53e9d939ac17d6f93793bce2e6f`. Check the current reviewed PR head in case it advanced. The collector entrypoint and P0 Make targets are not yet merged into `dev` or this P1 checkout, so use the separate clone below. Publishing code, a CI pass or the historical snapshot does not itself satisfy G0.

The PR carries, on its own branch:

- [tools/platform/inventory.py](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/tools/platform/inventory.py): read-only `collect` (explicit `--environment`, `--repo-root`, `--artifact-root`, optional `--context`) and `validate` (latest or `--input`-selected inventory) subcommands; Docker and repository metadata only; never runs `docker exec`, never reads `.env` contents, and never emits container environment values.
- [Makefile](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/Makefile): the two P0 targets `platform-inventory` and `platform-inventory-validate` with `PYTHON` and `PLATFORM_ARTIFACT_ROOT` variables; it is independent of this checkout's P1 Makefile and must never overwrite it (A1.6).
- [inventory.schema.json](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/infra/pulumi/shared/inventory.schema.json) (`anitrend.platform.inventory.v1`) and [environment.schema.json](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/infra/pulumi/shared/environment.schema.json) (`anitrend.platform.environment.v1`): the pinned schemas the validator enforces.
- [docs/platform/live-inventory.md](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/docs/platform/live-inventory.md): the dated sanitized snapshot with its recorded limitations.
- [Inventory tests](https://github.com/AniTrend/local-stack/tree/docs/platform-inventory-653/tests/platform): 30 passing offline cases cover synthetic Docker collection, actual JSON value types and complete reconciliation rules. CI runs the entire directory with read-only permissions. These tests do not replace the actual disposable-daemon acceptance.

Until the PR merges through repository policy, run it from its own disposable anonymous clone (A1.1). The manual read-only method in A2/A3 stays the fallback for host facts the collector does not cover.

The PR's snapshot report ([docs/platform/live-inventory.md](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/docs/platform/live-inventory.md)) remains the authoritative status read: G0 blocked, its Docker engine recorded as a source-host candidate rather than an owner-confirmed production identity, 37 unresolved environment inputs, and an explicit statement that its tests are synthetic and no disposable Docker daemon was designated for the issue's fixture acceptance.

#### A1.1 Obtain the collector without the original machine

Operator location: your workstation shell. Mutation scope: one new directory under your home. Works with Git and the Docker CLI only; anonymous HTTPS, no GitHub account, no SSH keys, and no path from an earlier machine. Your main checkout from workstation.md Stage 1 stays untouched.

```sh
# Anonymous, single-branch clone into a dedicated path (never inside the main checkout):
git clone --single-branch --branch docs/platform-inventory-653 \
  https://github.com/AniTrend/local-stack.git "$HOME/Git/local-stack-inventory"

# Verify the reviewed head before running anything (record the full SHA for evidence;
# a review-repair push advances the head, so compare against the PR page first):
git -C "$HOME/Git/local-stack-inventory" status --short --branch   # expect clean tree
git -C "$HOME/Git/local-stack-inventory" rev-parse HEAD            # compare with the reviewed PR head; repaired baseline: eb48f84bb584b53e9d939ac17d6f93793bce2e6f
```

A clean committed clone matters: the collector records `collector_commit` and `collector_worktree_clean` in every artifact, so a run from this clone is attributable to the PR head commit, while a run from an edited tree is not a clean-candidate record. If the branch advanced since your clone, fetch and fast-forward it; never edit files in the clone. When the work is done you may delete the whole directory; nothing outside it was created except the private artifact root from A1.2.

#### A1.2 Run the read-only lab collection (explicit local context, private artifacts)

Use the already installed P1 venv interpreter by absolute path (workstation.md Stage 3 built `.venv-platform` in your main checkout; it pins jsonschema and PyYAML, which the collector imports). The PR Makefile's `PYTHON ?= python3` fallback exists only for machines without the venv and must not be relied on: the system `python3` lacks those libraries.

```sh
# Operator location: workstation shell. Mutation scope: none on Docker; writes only under
# PLATFORM_ARTIFACT_ROOT (owner-only directories/files), never inside either checkout.
P1="$HOME/Git/local-stack"                          # main checkout from workstation.md Stage 1
P0="$HOME/Git/local-stack-inventory"                # A1.1 clone
PYTHON="$P1/.venv-platform/bin/python"              # absolute path; never a bare interpreter name
"$PYTHON" --version                                 # must print the pinned Python (3.14.9 at the time of writing)

# Restricted artifact root OUTSIDE both public checkouts:
mkdir -m 700 -p "$HOME/.local/state/platform-inventory"
export PLATFORM_ARTIFACT_ROOT="$HOME/.local/state/platform-inventory"

# P0's Docker contract variable is DOCKER_CONTEXT (NOT the P1 runners'
# PLATFORM_DOCKER_CONTEXT / PLATFORM_ALLOWED_DOCKER_CONTEXTS allowlist pair).
# Always pass it explicitly: omitting it would make the collector reuse whatever
# context the Docker CLI has selected, which this runbook forbids as blind
# source or production selection.
export DOCKER_CONTEXT=default                       # your local lab context from workstation.md Stage 2
docker context inspect "$DOCKER_CONTEXT" --format '{{json .Endpoints.docker}}'
#   must show a local socket endpoint, for example {"Host":"unix:///var/run/docker.sock"}

cd "$P0"
make platform-inventory ENV=lab DOCKER_CONTEXT="$DOCKER_CONTEXT" \
  PYTHON="$PYTHON" PLATFORM_ARTIFACT_ROOT="$PLATFORM_ARTIFACT_ROOT"
```

Expected output (one line, exit 0; your run ID differs):

```
inventory=20261027T183959Z-fcf5c1ad/inventory.json schema=valid reconciliation=blocked
```

What the command does and does not do: it runs `docker context inspect`, `docker version`, `docker info`, `docker ps -a`, `docker inspect`, `docker image inspect`, `docker stats --no-stream`, and `docker system df -v` against the one explicitly selected context, parses the repository's Compose sources, and writes `<PLATFORM_ARTIFACT_ROOT>/<run-id>/inventory.json` with directory mode 0700 and file mode 0600, git-ignored. `ENV=lab` refuses a remote endpoint before enumerating anything (`ENV=lab requires an explicitly selected local Docker endpoint`), so the lab path cannot reach a source or production engine by construction. The legacy source-host path is separate and owner-approved (A1.3); never select a source or production context by habit or blind reuse.

#### A1.3 Validate the selected inventory and the separate owner-approved legacy path

Validation is read-only and never re-collects. Validate the exact artifact by passing `INVENTORY_FILE`:

```sh
# Set RUN_ID to the run ID printed by A1.2 (the directory name holding inventory.json).
RUN_ID="20261027T183959Z-fcf5c1ad"                  # example; use YOUR printed run ID
make platform-inventory-validate ENV=lab \
  INVENTORY_FILE="$PLATFORM_ARTIFACT_ROOT/$RUN_ID/inventory.json" \
  PYTHON="$PYTHON" PLATFORM_ARTIFACT_ROOT="$PLATFORM_ARTIFACT_ROOT"
```

Expected output (exit 0): `schema=valid gate=blocked`.

With `INVENTORY_FILE` omitted, validation silently picks the newest inventory for that `ENV` under `PLATFORM_ARTIFACT_ROOT`; pass the file explicitly for any evidence-bearing run so the record identity is unambiguous. `ENV=legacy` validation works the same way against a legacy artifact.

For the legacy path, only the source host's owner may approve it: after recorded approval, rerun the A1.2 collect with `ENV=legacy DOCKER_CONTEXT=<owner-approved context>` (the artifact records `context_name` and `endpoint_kind`, for example `remote_ssh`), then reconcile the environment inputs on a private copy per A1.5 before re-validating with `INVENTORY_FILE`. Never run legacy against a context without the owner's recorded approval, and never relabel a source or production engine as `lab`.

#### A1.4 What a run proves: structural validity only

Exit 0 with `schema=valid` means the JSON matches the pinned `anitrend.platform.inventory.v1` and `anitrend.platform.environment.v1` schemas and that the recorded reconciliation decision is internally consistent. It is a structural statement about one file; it does not prove the host was observed, that the collector is accepted, or that G0 progressed. `gate=blocked` is the expected outcome: the collector writes `reconciliation.decision: blocked` with standing reasons (source host role and production identity not owner-confirmed; service dispositions, ownership, writer/job schedules, external providers, and recovery paths unreconciled; target, network, credential-reference, backup, and cutover inputs unresolved), and the validator refuses a hand-edited `pass` while required fields stay unresolved or `ENV=lab` is used at all (`reconciliation gate cannot pass from ENV=lab inventory`).

Two separate acceptance items remain open and are NOT satisfied by a valid schema:

1. Actual disposable-daemon fixture acceptance: the PR's tests use a synthetic Docker CLI fixture, and the PR explicitly records that no disposable Docker daemon was designated for this acceptance. Designate one throwaway daemon you own, run A1.2 against it with a recorded context name, and treat that as the fixture acceptance record.
2. Live host owner reconciliation: the A2/A3 host facts and the owner-approved identity inputs require the host owner; no collector run substitutes for them.

A schema-valid run that lacks either item stays recorded as blocked; blocked is never a pass.

#### A1.5 Reconcile and publish without exposing JSON or raw values

The private artifact (`inventory.json`) contains container IDs, image digests, volume names/sizes, mount source paths, network aliases, resource usage, explicitly scoped collector-host timers and the environment contract. It stays in restricted storage (`$PLATFORM_ARTIFACT_ROOT`) and is never committed or attached to a public issue. A local Docker socket does not prove those timers ran on the Docker engine's host. Independently confirm the source host's real writers/jobs before reconciling G0.

Publishing follows the PR's sanitized snapshot pattern ([docs/platform/live-inventory.md](https://github.com/AniTrend/local-stack/blob/docs/platform-inventory-653/docs/platform/live-inventory.md)): dated observation, collector run ID, engine facts, and per-service rows with counts, names, states, digests, and explicit limitation statements. Omit private host paths, raw addresses, unmatched workload names, timer unit names, and every raw export; the PR's own snapshot deliberately omits them.

Environment inputs are reconciled on a private copy of the inventory, then re-validated through A1.3 with `INVENTORY_FILE`: each input is a typed `{status, value, evidence_ref}` object where `status` is `confirmed`, `unresolved`, or `not_applicable`; `confirmed` requires a non-null value plus a non-null opaque `evidence_ref`; `unresolved` and `not_applicable` require null values. Credential fields (`credential_refs`, `recovery_credential_refs`) accept reference names only (`^[A-Za-z0-9_.:/-]+$`), never secrets. The public report states only which inputs are confirmed or unresolved, never their values.

The current G0 pass check requires all 37 production environment inputs to be confirmed with concrete values and evidence references. `not_applicable` may document an intermediate blocked record, but this contract defines no automatic exemption that makes G0 pass. Every observed container must map to exactly one known service or an explicit unmatched-owner/disposition record; blank or unresolved owners, mismatched contexts and missing confirmed health/database facts prevent pass. Recollect pre-repair artifacts that still have the old timer field instead of editing their labels into passing evidence.

#### A1.6 Reviewing and merging PR #673 (preserve both Makefile target sets)

Review path (read-only on this checkout): open [the PR files](https://github.com/AniTrend/local-stack/pull/673/files) and check that (1) the two Makefile target sets coexist, (2) the validator loads its schema pins from `infra/pulumi/shared/`, (3) the tests pass without a daemon, (4) no raw inventory, environment values, or credential material is committed, and (5) the CI job runs with read-only permissions. The PR stays a draft until its acceptance gates are satisfied; reviewers follow repository policy.

Integration rule: the PR's root Makefile carries only the two P0 targets (`platform-inventory`, `platform-inventory-validate`) plus the `PYTHON`/`PLATFORM_ARTIFACT_ROOT` defaults, while this checkout's root Makefile carries the P1 target set (`platform-doctor`, `platform-lab-up`, `platform-lab-test`, `platform-lab-down`, `platform-pulumi-test`, `platform-preview`, `platform-ansible-test`, `platform-host-verify`, `platform-evidence-validate`) with its own `PLATFORM_PYTHON_BIN` variable and a fail-closed `.DEFAULT` rule. These are independent target sets from two branches. When the PR merges (after review, through repository policy), combine the Makefiles by hand: append the two P0 targets and their variables to the P1 Makefile (or the agreed shared shape), keep every existing target, and keep the fail-closed default so unimplemented commands still exit 2. Never overwrite the P1 Makefile with the P0 one or the reverse, and never delete a target set to "fix" a conflict. Until the merge lands, this checkout's missing targets are correct fail-closed behavior, not a defect to patch by copying files.

### A2. Safety rules for collection

The A1 lab collection touches only your explicitly selected local Docker context and writes only to the private artifact root; the rules below govern the eventual live-host run.

- Operator location: an SSH or cloud-console session on the live host, using an account with read access. Mutation scope: none. Every command in this part is read-only (`docker inspect`, `docker ps`, `findmnt`, `apt list --installed`, version queries). Do not restart, prune, upgrade, or edit anything on the live host.
- Raw `docker inspect` output, process environments, APISIX consumer exports, and database data can contain secrets. Keep raw dumps only in restricted storage (an independent encrypted location outside this public repository). Commit only sanitized facts and opaque references to that storage.
- Never enable PostgreSQL or Unleash "to test", never start the excluded stacks, and never mutate the Doco-CD runner or its workspace while collecting.

### A3. Missing live inventory facts and how to close them

The first column is the fact; the second is the acquisition method (all read-only, from the host); the third names who authorizes host access; the fourth is the check or stop condition. Any row you cannot close stays an explicit blocker in the issue; missing host access blocks this gate but not offline lab work.

| Missing fact | How to obtain (read-only, on the host) | Authorized by | Check / stop condition |
|---|---|---|---|
| Actual container/service list, image digests and architectures | `docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}'`, `docker inspect <name> --format '{{.Image}}'`, `docker image inspect <digest> --format '{{.Os}}/{{.Architecture}}'` | Host owner | Every service in current-state.md's map either observed live or recorded absent; unknown extra services get their own records |
| PostgreSQL data major and PGDATA | `psql --version` inside the running container or `cat /var/lib/postgresql/data/PG_VERSION` on the mounted volume | Host owner + data owner | Major recorded before any migration image is chosen; the source comment says PG17 while the image is 18; preserve the observed major |
| Mongo storage layout | `docker inspect` volume mounts of the mongo container; `du -sh` per data directory inside the volume | Host owner + data owner | Resolved whether one named volume really serves both `/data/db` and `/data/configdb` (closed #504 is not runtime proof) |
| Redis persistence reality | `redis-cli CONFIG GET appendonly` (read-only), volume identity via `docker inspect` | Host owner + data owner | Durable vs disposable classified with owner evidence; AOF is enabled in source, do not assume a cache |
| APISIX runtime configuration | Export routes/services/upstreams/consumers/plugins/global-rules from etcd via the APISIX admin API or `etcdctl get --prefix` (read-only); secrets redacted | Gateway owner | Export stored restricted; public summary lists plugin names and policies without tokens |
| Traefik live provider and exposure | `docker inspect traefik` (mounts, socket), live `traefik` API if enabled read-only, label inventory across containers | Host owner | Confirm Docker provider vs Swarm, whether the dashboard is really off, and the certificate volume identity |
| Deployment controllers and ownership | `docker service ls` (Swarm), Portainer state, Doco-CD container state, local-stack-deployer logs (read-only) | Host owner | One observed owner per workload; Doco-CD's secrets-mode stack-selector defect confirmed or refuted on the running image |
| Runtime-only services, especially any relations backend absent from this tree | `docker ps` cross-check against repository sources; check image labels and compose origins | Host owner | Any service without repository source is traced to its owning repository and recorded |
| Published ports IPv4/IPv6 and network attachments | `docker ps --format '{{.Ports}}'`, `docker network inspect <name>`, `ss -tlnp` (read-only) | Host owner | Public/private classification recorded for the firewall intent |
| Volumes, data sizes, backup state | `docker volume ls`, `docker system df -v`, existing backup cron/log review | Host owner + data owner | Current backup method per store recorded or recorded as absent |
| Environment contract inputs: Hetzner project/location, target architecture/server type, DNS provider/zone/records/TTL, private hostname/certificate approach, tailnet identity/grants, Pulumi state backend, backup destination and recovery credentials, RPO/RTO, maintenance window, maximum downtime, rollback thresholds | Platform owner supplies values; each becomes a typed `{status, value, evidence_ref}` input of the production environment contract `anitrend.platform.environment.v1` in PR #673's `infra/pulumi/shared/environment.schema.json` (37 inputs, all starting `unresolved`; reconciled on a private copy per A1.5, never published raw) | Platform owner; deviations from ADR defaults need recorded evidence | Missing production inputs block the applicable gate; synthetic lab values must be visibly marked |
| Database and gateway data versions to preserve | Version queries above; record image digest plus on-disk major | Data owner | No database major upgrade is bundled into the migration; this fact guards that rule |

### A4. P0 outputs

When closed, P0 produces: the sanitized `docs/platform/live-inventory.md` (observation time, source commit, host facts, one record per service per the current-state schema), the validated non-secret environment contract and decision record described in issue #653, and the private normalized artifact kept in restricted storage per A1.2/A1.5. Collection commands must themselves be reviewed as read-only and exercised once on a disposable fixture before being run against the live host; the PR's synthetic-fixture tests (A1.4) are not that disposable-fixture run.

## Part B: local T1 acceptance for #654, #655, #656 (summary)

Full setup and lab commands are in [workstation.md](workstation.md) Stage 4. Per-item acceptance that runs locally:

- #654: `make platform-doctor ENV=lab` then `platform-lab-up`, `platform-lab-test`, `platform-preview`, `platform-lab-down` all exit 0; the manifest at `.artifacts/platform/lab/<run-id>/manifest.json` records the commit, architectures, fixture digest, no-op second update, controlled update, and cleanup. An unrelated container you create yourself before `up` still exists after `down`.
- #655: `make platform-pulumi-test ENV=lab` runs the Docker-provider, HCloud-intent, and platform Python tests; `make platform-preview ENV=lab` diffs the active lab stack without creating or applying anything.
- #656 (container tier): `make platform-ansible-test ENV=lab` converges the digest-pinned Ubuntu 24.04 Molecule fixture, proves zero-change idempotence and drift repair, and cleans only its own run-labelled container.

macOS arm64 note: the lab reports `execution_mode` in the doctor output. Emulated execution is recorded, never silently claimed as native coverage; before any production-relevant gate, rerun the failing piece natively on the target architecture (the lab VM tier below is amd64/arm64 native by schema).

## Part C: full VM tier acceptance, `make platform-host-verify ENV=lab TIER=vm`

This is the P1-03 VM acceptance and the T2 tier of [validation.md](../validation.md#ansible-execution-and-prerequisites). It runs real Ansible against one disposable native Ubuntu 24.04 VM you provide. It never provisions HCloud resources.

### C1. Obtain a fresh disposable Ubuntu 24.04 VM (chosen owner)

Operator: you, as the VM's owner. Mutation scope: the VM only. Any owner works as long as you have console access and the VM has a native architecture: a local hypervisor VM (for example Multipass, UTM, QEMU/VirtualBox, GNOME Boxes), a spare physical machine, or an already-owned cloud VM. Do not use the production host, and do not create Hetzner resources for this tier (that is T3, gated later).

Requirements enforced by the code: Ubuntu 24.04 with systemd (`vm-verify.yml` asserts distribution, version, and `service_mgr`), architecture `amd64` or `arm64` matching the inventory, and native execution (`native_execution` is a schema constant; do not run an emulated VM). Record the exact image identity you used (for example `Ubuntu 24.04 LTS cloud image amd64, revision X`) for evidence.

Size the disposable VM for systemd, Docker, Tailscale and reboot/storage checks, with a separate scratch disk. A 2 GiB RAM / 10 GiB system disk starting point is planning guidance, not measured VM acceptance; the workstation doctor's similar floor does not establish guest capacity. Increase it if package installation, disk pressure or observed resource use requires it, and record the actual VM sizing.

### C2. Attach a blank scratch disk for the storage test

The declared storage volume must be a real block device addressed by a stable `/dev/disk/by-id/` path. Easiest reproducible path: attach one empty disk to the VM before first boot (hypervisor "add disk"). On the VM console, read-only:

```sh
ls -l /dev/disk/by-id/          # pick the identifier of the empty scratch disk (virtio: /dev/disk/by-id/virtio-..., scsi: scsi-0HC_... or ata-...)
lsblk                           # confirm it is blank (no partitions) and note its size
```

You will declare this device with `format_policy: "create-only"` and `data_classification: "empty"`, which authorizes Ansible to create one ext4 filesystem on a device that `blkid`/`wipefs` confirm carries no signatures. Any other filesystem signature on the device aborts the run. The alternative is `format_policy: "never"` on a disk you formatted and mounted yourself.

### C3. Verify the VM SSH host key from the console (never blind-trust)

Operator location: the VM console (hypervisor window or provider console). Mutation scope: none.

```sh
sudo awk '{print $1, $2}' /etc/ssh/ssh_host_ed25519_key.pub
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk '{print $2}'
```

Record only the first command's two fields (`ssh-ed25519` and the base64 payload), with no trailing key comment. Record only the second command's `SHA256:...` token. These exact values go into C6's signed trust bundle; the schema rejects comments and descriptive fingerprint text. The runner enforces `StrictHostKeyChecking=yes`. If the VM is recreated, repeat C3 and re-establish its identity through the authenticated console before signing a new bundle.

### C4. Bootstrap access on the VM (complete C5 first)

The runner first connects as the inventory's `bootstrap_user` using `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY`, and `bootstrap-host.yml` creates the fixed automation account `platform-automation` (its `authorized_keys` file is exclusively managed to contain exactly the declared Ed25519 automation key, with password-locked login and passwordless sudo). The bootstrap user must already exist with the bootstrap public key installed and passwordless sudo: every playbook runs with `become: true` and no become password is ever supplied, so plain group membership is not enough.

Prerequisite: complete C5 (key generation) first; C4 installs the generated `bootstrap_ed25519.pub`. Replace `<connect_address>` with your VM's real address everywhere below.

1. On the workstation, print the actual public key you will install:

   ```sh
   cat ~/platform-keys/bootstrap_ed25519.pub
   ```

2. On the VM console, create the bootstrap user (or use the image's existing default user, for example `ubuntu`, and keep its own key as recovery):

   ```sh
   sudo adduser --disabled-password --gecos '' ansible
   ```

3. Install the real key. Preferred path, from the workstation, using the VM's default user and its existing key:

   ```sh
   VM_ADDRESS="192.0.2.18"   # your VM's connect_address (C7); replace with the real value
   scp -o IdentitiesOnly=yes ~/platform-keys/bootstrap_ed25519.pub \
     "ubuntu@$VM_ADDRESS":/tmp/bootstrap.pub
   ```

   Then on the VM console:

   ```sh
   sudo mkdir -p /home/ansible/.ssh && sudo chmod 700 /home/ansible/.ssh
   sudo tee -a /home/ansible/.ssh/authorized_keys </tmp/bootstrap.pub >/dev/null
   sudo chown -R ansible:ansible /home/ansible/.ssh && sudo chmod 600 /home/ansible/.ssh/authorized_keys
   rm /tmp/bootstrap.pub
   ```

   Fallback when SSH transfer is not available yet: create `/home/ansible/.ssh/authorized_keys` in the console editor and paste the exact single line printed in step 1 (it starts with `ssh-ed25519 `), then apply the same ownership and mode commands. Never paste a placeholder line.

4. Grant passwordless root escalation to this bootstrap user only (the runner never supplies a become password). On the VM console, create a user-specific visudo-validated drop-in:

   ```sh
   printf '%s\n' 'ansible ALL=(root) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/90-platform-bootstrap >/dev/null
   sudo chmod 0440 /etc/sudoers.d/90-platform-bootstrap
   sudo visudo -cf /etc/sudoers.d/90-platform-bootstrap   # must print: parsed OK
   ```

   Scope: this grants root escalation to the bootstrap user on this disposable VM only, matching the platform's own automation-account pattern (`/etc/sudoers.d/90-platform-automation`, mode 0440, visudo-validated). On shared or production tiers, follow that environment owner's sudo policy instead.

5. Verify both requirements from the workstation before running the tool (reuse the same `VM_ADDRESS` shell):

   ```sh
   ssh -i ~/platform-keys/bootstrap_ed25519 -o IdentitiesOnly=yes \
     "ansible@$VM_ADDRESS" 'sudo -n true && printf "sudo-ok\n"'
   ```

   A password prompt or `sudo: a password is required` means step 4 is wrong; a permission error means step 3 is wrong. Fix before continuing; the runner would fail later at the same wall.

Keep the image's own default user untouched as independent recovery access; recovery after firewall changes remains with the bootstrap account by design.

### C5. Generate the keys (workstation shell, restricted storage)

Operator location: your workstation, in a private directory outside the repository. Mutation scope: your key directory only. Keys stay here; nothing is committed.

```sh
mkdir -p ~/platform-keys && chmod 700 ~/platform-keys && cd ~/platform-keys

# Bootstrap SSH keypair (OpenSSH format, Ed25519)
ssh-keygen -q -t ed25519 -N '' -C 'platform bootstrap lab' -f bootstrap_ed25519

# Automation SSH keypair; the runner requires the private key file mode 600
ssh-keygen -q -t ed25519 -N '' -C 'platform automation lab' -f automation_ed25519
chmod 600 automation_ed25519

# Ed25519 trust root (PEM, not OpenSSH format): the adapter loads a PEM public key
cat > generate-trust-root.py <<'PY'
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.generate()
Path("trust-root-private.pem").write_bytes(key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
Path("trust-root-public.pem").write_bytes(key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
PY
REPO="$HOME/Git/local-stack"   # your checkout from workstation.md Stage 1
"$REPO/.venv-platform/bin/python" generate-trust-root.py
chmod 600 trust-root-private.pem
```

Use the checkout's venv Python (cryptography 50.0.2 from `tools/platform/requirements.lock`); recreate the venv per workstation.md Stage 3 if the checkout is new. For a personal disposable lab an empty SSH passphrase is acceptable only because the key directory is private and the VM is disposable; production tiers use protected keys and separate trust roots per environment. Copy `bootstrap_ed25519.pub` into the VM per C4.

### C6. Signed SSH host trust bundle (exact schema and workflow)

The adapter (`tools/platform/ansible_inventory.py`) validates the bundle against `infra/pulumi/shared/ssh-host-trust.schema.json` (version `anitrend.platform.ssh-host-trust.v1`) and verifies an Ed25519 signature over the canonical JSON of every field except `signature` (`sort_keys=True`, separators `(",", ":")`, UTF-8, no whitespace), base64-standard-encoded. The trust root public key must be supplied as a separate PEM file; the runner rejects a bundle that equals the trust root file.

Create `trust-bundle.json` next to the keys, filling C3's recorded values:

```json
{
  "schema_version": "anitrend.platform.ssh-host-trust.v1",
  "environment": "lab",
  "identity_ref": "host-identity:lab:platform-lab-01",
  "trust_type": "host_key",
  "host": {
    "address": "192.0.2.18",
    "public_key": "ssh-ed25519 AAAA...the value from /etc/ssh/ssh_host_ed25519_key.pub",
    "fingerprint_sha256": "SHA256:...the value printed by ssh-keygen -lf"
  }
}
```

Field rules: `address` must equal the inventory host's connect address exactly (IPv4 or IPv6); `identity_ref` must equal the inventory's `expected_host_identity_ref`; `environment` must be `lab`; `trust_type` is `host_key` for a single key or `host_ca` for a CA (then `known_hosts` gets a `@cert-authority` line). Sign it with the trust root private key:

```sh
cat > sign-trust-bundle.py <<'PY'
"""Sign the SSH host trust bundle exactly as the platform adapter verifies it."""
import base64, json, sys
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key

private_pem, bundle_path = Path(sys.argv[1]), Path(sys.argv[2])
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
message = json.dumps(
    {k: v for k, v in bundle.items() if k != "signature"},
    sort_keys=True, separators=(",", ":"),
).encode("utf-8")
signer = load_pem_private_key(private_pem.read_bytes(), password=None)
bundle["signature"] = base64.b64encode(signer.sign(message)).decode("ascii")
bundle_path.write_text(json.dumps(bundle, indent=2) + "\n")
print("signed", bundle_path)
PY
"$REPO/.venv-platform/bin/python" sign-trust-bundle.py trust-root-private.pem trust-bundle.json
chmod 600 trust-bundle.json
```

(`$REPO` is the checkout path set in C5. The snippet uses the pinned `cryptography` library for Ed25519 signing, exactly matching the adapter's verification and the repository's own test helper; it deliberately does not use `ssh-keygen -Y`, whose signature format differs.)

This is the same signing workflow the repository's own tests use (`tests/platform/test_ansible_inventory.py`); keep the private trust root in restricted storage, because anything it signed will be trusted as a host key.

### C7. Lab VM inventory (complete synthetic example)

The runner validates the inventory against `infra/pulumi/shared/lab-vm-inventory.schema.json` (version `anitrend.platform.pulumi-inventory.lab-v1`, provider constant `external-vm`, environment constant `lab`, exactly one host, at least one volume). Create `lab-vm-inventory.json`. Every value shown is SYNTHETIC (RFC 5737 documentation addresses) and visibly marked; replace each field with your VM's real value before running:

```json
{
  "schema_version": "anitrend.platform.pulumi-inventory.lab-v1",
  "environment": "lab",
  "stack_identity": "external-vm:platform-lab-01",
  "provider": "external-vm",
  "ssh_source_cidrs": ["192.0.2.10/32"],
  "hosts": [
    {
      "resource_id": "platform-lab-01",
      "name": "platform-lab-01",
      "bootstrap_user": "ansible",
      "connect_address": "192.0.2.18",
      "architecture": "amd64",
      "os_image": "ubuntu-24.04",
      "expected_host_identity_ref": "host-identity:lab:platform-lab-01"
    }
  ],
  "volumes": [
    {
      "resource_id": "platform-lab-data-01",
      "reference": "platform-lab-data",
      "linux_device": "/dev/disk/by-id/virtio-platform-lab-data",
      "filesystem": "ext4",
      "format_policy": "create-only",
      "mount_path": "/srv/anitrend/platform-lab-data",
      "size_gb": 10,
      "data_classification": "empty",
      "protected": false
    }
  ],
  "architecture": "amd64",
  "image_ref": "ubuntu-24.04",
  "native_execution": true,
  "readiness": "ready"
}
```

How to obtain each real value, and who authorizes it:

| Field | Real value comes from | Authorized by | Check / stop condition |
|---|---|---|---|
| `stack_identity` | Your chosen label for this VM run, unique per environment | You | Reuse the same value on re-runs of the same VM; never share one identity across VMs |
| `ssh_source_cidrs` | The address the VM sees as the SSH peer. Establish the console-verified connection, then on the VM console use `ss -tn 'sport = :22'` to read its peer. Declare a single IPv4 peer with `/32`, or a single IPv6 peer with `/128` | You for a lab VM; platform owner for shared tiers | The firewall role aborts before changes if the live SSH peer is not covered. Do not widen an IPv6 host to `/32` or normalize away host bits to work around a rejected CIDR |
| `hosts[0].bootstrap_user` | The user you prepared in C4 (pattern `^[a-z_][a-z0-9_-]{0,31}$`) | You | Key installed and passwordless sudo verified by C4 step 5; the run aborts otherwise |
| `connect_address` | The VM's address reachable from your workstation | You | Must equal the trust bundle `host.address` byte for byte |
| `architecture` / `hosts[].architecture` | `uname -m` on the VM console: `x86_64` maps to `amd64`, `aarch64` to `arm64` | You | Must match the real guest; the Tailscale role cross-checks it against the host architecture |
| `os_image` / `image_ref` | The image identity you recorded in C1 | You | Must be Ubuntu 24.04 or verification fails |
| `expected_host_identity_ref` / trust `identity_ref` | Your stable identity label for this host; identical in both files | You | Mismatch fails the run before any connection |
| `volumes[0].linux_device` | The stable `by-id` path from C2 (must match `^/dev/disk/by-id/[^\s]+$` and be a direct child, never `.` or `..`; traversal is rejected before device inspection) | You | `stat` on the path resolves to a block device; the declared device must not already be mounted elsewhere |
| `format_policy` / `data_classification` | `create-only` + `empty` for the C2 blank disk; `never` + your own classification for a pre-formatted disk | You, explicitly | `create-only` additionally requires the exact confirmation variable from C10 |
| `mount_path` | One of `/srv/...`, `/mnt/...`, `/var/lib/...`, for example `/srv/anitrend/platform-lab-data` | You | Must not overlap another declared mount path or an existing foreign mount |
| `size_gb` | The disk's real size | You | Hetzner tiers enforce 10 to 10000 GB; keep lab values realistic |
| `readiness` | `ready` only when you actually intend the run | You | Anything else is rejected |

### C8. Tailscale ACL tag and auth key

Operator location: Tailscale admin console (web UI) plus the tailnet policy file. The runner requires `PLATFORM_TAILSCALE_TAG` matching `^tag:[a-z0-9][a-z0-9-]{0,62}$` and a single-line `PLATFORM_TAILSCALE_AUTH_KEY`. The tailnet admin (you or your tailnet owner) authorizes:

1. In the tailnet policy (Access Controls), define the tag and its owner, least privilege, for example:

   ```json
   "tagOwners": {
     "tag:platform-lab-vm": ["autogroup:admin"]
   }
   ```

   Use the exact approved tag value everywhere; if your tailnet has a naming convention or requires an owner's approval, get it. No other ACL grant is needed for this test: the VM only needs to enroll and reach `Running` state.

2. Generate one auth key: admin console, Settings, Keys, Generate auth key. Scope it to the tag above (pre-approved tags), single-use, short expiry (hours), not ephemeral (the node should persist through the reboot test). See [Tailscale auth keys](https://tailscale.com/kb/1085/auth-keys) and [tags](https://tailscale.com/kb/1068/acl-tags).

3. Hand the key to the run safely. The Ansible role never echoes it: it writes it to a root-only `/run/platform-tailscale-auth-key` file on the VM (mode 0600), enrolls with `tailscale up --auth-key=file:...` plus fixed safe flags (no advertised routes, no exit node, `--ssh=false`, `netfilter-mode=on`, `accept-dns=false`), and deletes the key file afterwards. On your workstation, pass it through a private env file, never through shell history or `set -x`:

   ```sh
   umask 077
   cat > ~/platform-keys/vm-lab.env <<'EOF'
   export PLATFORM_TAILSCALE_AUTH_KEY=tskey-auth-...
   export PLATFORM_TAILSCALE_TAG=tag:platform-lab-vm
   EOF
   chmod 600 ~/platform-keys/vm-lab.env
   ```

   Revoke the key in the admin console after the run. The runner and Ansible roles strip or `no_log` these values, and the evidence manifest never contains them.

### C9. Docker and IPv6 hook preconditions on the VM

The platform roles deliberately do not install Docker (that ownership arrives with the Dokploy bootstrap in P2). The VM verification, however, checks the Docker forwarding policy (`DOCKER-USER` chain) and requires `docker.service` active after reboot, so the VM must already run Docker Engine from the official Ubuntu instructions ([docs.docker.com/engine/install/ubuntu](https://docs.docker.com/engine/install/ubuntu/)). Do not initialize Swarm on it; Dokploy owns that topology later.

Failure behavior, enforced by code and tests:

- Docker IPv4 `DOCKER-USER` hook missing (Docker absent or not running) is a hard firewall error: `Docker IPv4 DOCKER-USER hook is unavailable`.
- If the VM has IPv6 (non-link-local address or default route), the firewall policy records `ipv6_enabled: true` and the Docker IPv6 `DOCKER-USER` hook must exist as well (Docker with ip6tables enabled creates it; see [Docker packet filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/)). A missing IPv6 hook while host IPv6 filtering is enabled is an explicit gate failure, not a skipped pass (`Docker IPv6 filtering is unavailable while host IPv6 filtering is enabled.`). If your VM has no IPv6 at all, the requirement disappears with it.

### C10. Storage guard and required inputs

Format confirmation (exact string, needed whenever any declared volume uses `format_policy: "create-only"`):

```sh
export PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT=I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES
```

The runner refuses to proceed when the inventory permits create-only formatting and this exact confirmation is absent; the storage role then additionally verifies the device carries zero recognized signatures before `mkfs` (without force). All refusal checks happen before any mutation: an unknown or foreign filesystem is refused, a device mounted somewhere other than its declared path is refused, and a volume already mounted at its declared path from the declared device is preserved and verified (device identity and filesystem-root metadata), never reformatted.

Complete input table (all set in the same private env file from C8; the runner checks them before any connection and reports every missing name together):

| Variable | Value | Notes |
|---|---|---|
| `PLATFORM_VM_INVENTORY` | path to `lab-vm-inventory.json` (C7) | must exist as a file |
| `PLATFORM_VM_TRUST_BUNDLE` | path to signed `trust-bundle.json` (C6) | must differ from the trust root file |
| `PLATFORM_VM_TRUST_ROOT` | path to `trust-root-public.pem` (C5) | PEM Ed25519 public key |
| `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY` | path to `bootstrap_ed25519` (C5) | mode must exclude group/other reads |
| `PLATFORM_VM_AUTOMATION_PUBLIC_KEY` | one-line contents of `automation_ed25519.pub` | must start `ssh-ed25519 ` |
| `PLATFORM_VM_AUTOMATION_PRIVATE_KEY` | path to `automation_ed25519` (C5) | mode must exclude group/other reads |
| `PLATFORM_TAILSCALE_AUTH_KEY` | single-line auth key (C8) | never echoed; revocable |
| `PLATFORM_TAILSCALE_TAG` | one approved tag, e.g. `tag:platform-lab-vm` (C8) | must match the tag pattern |
| `PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT` | exact confirmation string, only for create-only volumes | storage guard |
| `PLATFORM_DOCKER_CONTEXT` / `PLATFORM_ALLOWED_DOCKER_CONTEXTS` | local context + allowlist (workstation.md Stage 2) | still required; the runner refuses cloud credentials in the environment and runs its toolchain checks first |

### C11. Run and expected manifestations

Operator location: workstation shell, repository root, `feat/platform-ansible-656` checkout. Mutation scope: the target VM only (never HCloud; the runner is not wired to any cloud API).

```sh
source ~/platform-keys/vm-lab.env
export PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT=I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES
export PLATFORM_VM_INVENTORY=~/platform-keys/lab-vm-inventory.json
export PLATFORM_VM_TRUST_BUNDLE=~/platform-keys/trust-bundle.json
export PLATFORM_VM_TRUST_ROOT=~/platform-keys/trust-root-public.pem
export PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY=~/platform-keys/bootstrap_ed25519
export PLATFORM_VM_AUTOMATION_PUBLIC_KEY="$(cat ~/platform-keys/automation_ed25519.pub)"
export PLATFORM_VM_AUTOMATION_PRIVATE_KEY=~/platform-keys/automation_ed25519
make platform-host-verify ENV=lab TIER=vm
```

In order, the runner: validates the pinned toolchain (pinned Python, ansible-core, molecule, locked collections); validates the inventory and trust (schema, signature, environment match, address equality, fingerprint); then runs these playbooks, stopping at the first failure:

1. `bootstrap-host.yml` as the bootstrap user: creates `platform-automation` with your automation key, exclusive `authorized_keys`, sudo, and baseline account validation.
2. `reconnect-verify.yml` as `platform-automation`: proves a fresh SSH login as the new account before any firewall change.
3. `storage-identity-safety-verify.yml`: stable-`by-id` device identity and traversal checks.
4. `fresh-host.yml` as `platform-automation` with `platform_firewall_recovery_access_verified=true`: OS baseline packages, timezone, journald bounds (500 MiB system / 100 MiB runtime), storage convergence, Tailscale 1.104.2 from checksum-pinned archives, host firewall service.
5. `reconnect-verify.yml` again, now after the host firewall changed: the automation path must survive.
6. `storage-safety-verify.yml`: loopback-backed data/metadata preservation, refusal of unapproved formatting, explicit create-only path on a blank device.
7. `vm-verify.yml`: Ubuntu 24.04/systemd asserts, Tailscale `Running`, pinned Tailscale version evidence, firewall service active, INPUT and `DOCKER-USER` policy converged with no drift, injected tailnet-SSH-rule drift repaired, Docker IPv6 hook check per C9, mounts verified by device identity, then a controlled reboot with SSH/Tailscale/mount/firewall recovery checks.
8. `fresh-host.yml` a second time: the run fails unless the recap reports zero changed tasks.

On success it prints `platform-host-verify=pass evidence=.artifacts/platform/<run-id>/manifest.json`; the manifest records result `pass`, each step with command shape, exit code and changed counts, the inventory identity fields, the observed `tailscale` and `docker-client` versions, and the tested commit. Temporary generated inventory and `known_hosts` are removed after the run. Missing inputs produce `blocked: missing required VM inputs: ...` (exit 2) with no connection; a failed assertion produces `error: host verification step ... failed` and a `fail` manifest. Either way the artifact is valid evidence; neither is a pass.

Then validate the record and cite it by scope:

```sh
# Set RUN_ID to the run ID that platform-host-verify printed (format YYYYMMDDTHHMMSSZ-<8 hex>).
RUN_ID="20261026T101500Z-4c5d6e7f"   # example format; use YOUR printed run ID
make platform-evidence-validate ENV=lab TIER=vm \
  MANIFEST=".artifacts/platform/$RUN_ID/manifest.json" \
  COMMIT="$(git rev-parse HEAD)"
```

A pass prints `evidence-validation=pass scope=host-baseline`; that scope means the recorded host-baseline evidence is complete, passing, and bound to the tested commit. It is not a G0 to G6 gate approval, an authenticity claim, or a statement about the host's current state.

### C12. VM failure and recovery

| Symptom | Meaning and recovery |
|---|---|
| `blocked: missing required VM inputs: ...` | Set every named variable in the run shell (C10). |
| `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY must not be readable by group or other users` | `chmod 600` the key file. |
| `the supplied inventory or authenticated host trust was rejected` | The adapter refused schema/signature/environment/address/fingerprint data; re-verify C3 and C6 values against the actual VM (a recreated VM invalidates the old bundle by design). |
| `SSH host trust signature verification failed` | The bundle was altered after signing or signed by a different root; re-sign with C6's workflow. |
| `The active SSH peer is not covered by the declared SSH source CIDRs.` | Update `ssh_source_cidrs` in C7 to the real peer with `/32` for IPv4 or `/128` for IPv6, then rerun. Never widen the network as a workaround. |
| `blocked: inventory permits create-only storage formatting; set the exact PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT confirmation` | Export the exact string from C10. |
| Bootstrap playbook cannot connect | Test `ssh -i ~/platform-keys/bootstrap_ed25519 ansible@$VM_ADDRESS` (C4 step 5) manually; the strict SSH options require the trust and sudo setup to be right first. |
| `Docker IPv6 filtering is unavailable while host IPv6 filtering is enabled.` | Enable Docker's ip6tables (daemon `ipv6` + `ip6tables` per Docker docs) or use a VM without IPv6; do not weaken the policy. |
| Second convergence reports changes | Something outside the roles changed the host (manual edits, cloud-init); restore a clean VM and re-run. |
| Run died mid-way | Rebuild or restore the disposable VM from scratch and re-run end to end; the runner never resumes into a partially configured host, and all keys/inputs are unchanged. |

## Part D: HCloud preview readiness and the G0 stop (P1-02 cloud part)

Everything in this part is preparation only. No apply, no creation, no claim of a run.

1. Identity and state backend (when authorized for T3): a Hetzner Cloud project with an API token (least privilege; a read-scoped token suffices for previews) and a Pulumi Cloud account/organization for durable state. The preview wrapper (`tools/platform/pulumi_preview.py`) requires, for `ENV=rehearsal` or `ENV=production`, the Pulumi Cloud backend (`api.pulumi.com`) and the pinned CLI; log in once with `pulumi login` and do not export `PULUMI_ACCESS_TOKEN` in shells that also run lab commands. `ENV=lab` previews stay local and never need any account.
2. Stack configuration (created later under `infra/pulumi/hcloud/`; stack settings files `Pulumi.rehearsal.yaml` / `Pulumi.production.yaml` are Git-ignored): the stack name must equal the intent environment. Config namespaces follow `index.ts` and `Pulumi.yaml` exactly: the intent object is `anitrend-platform-hcloud:environment-intent` (the program reads `new pulumi.Config()`, whose default namespace is the project name `anitrend-platform-hcloud`) validated against `infra/pulumi/shared/environment-intent.schema.json` (project, region, server type, architecture, CIDRs, volumes, routes, DNS, state backend, backup destination, RPO/RTO, budget fields); the Hetzner project reference is `platform:hcloud-project-ref`; the token is the `hcloud:token` secret set with `pulumi config set hcloud:token --secret`. Intent fields `budget_limit_eur`, `estimated_monthly_cost_eur`, `cost_estimate_ref` and `ttl_hours` are enforced by the platform's own validation and review, not by a Hetzner billing feature; provider-side delete/replacement protection is enforced by the program itself, and preview classifies replacements and deletions.
3. G0 outbound-policy STOP: Hetzner Cloud Firewall egress is currently provider-default allow-all because the intent contract has no outbound allowlist. Do not apply rehearsal or production resources until G0 records the required outbound destinations and an authorized egress policy exists (implemented in the intent schema and reviewed). Until then `make platform-preview ENV=rehearsal|production` may only be run by an authorized operator against real credentials for classification purposes, and nothing may run `pulumi up`. This is an explicit blocker, recorded as blocked, not a passed criterion.

## Part E: acceptance evidence per work item

Assemble per [agent-execution.md](../agent-execution.md#required-issue-completion-evidence): implemented paths, PR, tested commit, exact commands, environment/tier, versions, digests, architectures, assertion results, cleanup, blockers. Before citing any manifest, validate it with `make platform-evidence-validate` (TIER=docker for lab-run records, TIER=vm for host-verify records) and quote the printed scope; a nonpassing, incomplete, mismatched, or unknown-schema record exits 2 and is a failed check, not a pass. The validator's output covers recorded evidence only; it never approves a G0 to G6 gate or vouches for current runtime state.

- #653: per A3, every row closed or explicitly blocked; sanitized `docs/platform/live-inventory.md` updated from a reviewed read-only collection; private inventory schema-validated per A1.3; raw data only in restricted storage per A1.2/A1.5. Current status: the collector is published as draft PR [#673](https://github.com/AniTrend/local-stack/pull/673) and reviewable per A1.6, but it is not merged into `dev` or this checkout, so G0 stays blocked: the disposable-daemon fixture acceptance (A1.4) and the owner-confirmed live host reconciliation are still open. Blocked is never a pass.
- #654: doctor/up/test/preview/down transcript plus `.artifacts/platform/lab/<run-id>/manifest.json`; unrelated-fixture survival note; negative tests (remote endpoint, missing context, credentials present) each shown refused; validated with `platform-evidence-validate ... TIER=docker` printing `scope=docker-lab-lifecycle` (it requires all lifecycle assertions passing, zero pending revision, cleanup complete, and run-scoped resource identities).
- #655: `platform-pulumi-test` results; lab preview no-op evidence; production-config preview classification only if authorized credentials exist; backend bootstrap and recovery notes; no apply anywhere.
- #656: `platform-ansible-test` Molecule results; `platform-host-verify` manifest from C11 validated with `TIER=vm` printing `scope=host-baseline` (the missing piece for closing the issue: full VM acceptance was not run as of PR #671); storage guard refusals demonstrated; second converge zero-changes recap.

## Troubleshooting (beyond Part C)

| Symptom | Fix |
|---|---|
| `blocked: PLATFORM_DOCKER_CONTEXT must be explicitly allowlisted` before the VM run | The same Docker context rules apply to the Ansible runners; re-export both variables. |
| `refusing to run with cloud or production credentials in the environment` | Unset `HCLOUD_TOKEN` and friends in that shell (workstation.md Stage 4 step 1); run Pulumi-only work in a separate shell. |
| `Ansible collections must be installed inside the repository` | `PLATFORM_ANSIBLE_COLLECTIONS_PATH` must resolve inside the checkout; use the Stage 3 default. |
| `pinned Ansible tool versions are missing or mismatched` | Reinstall the hash-locked venv and collections (workstation.md Stage 3). |
| `No rule for target "platform-inventory"` | Expected on this checkout until PR [#673](https://github.com/AniTrend/local-stack/pull/673) merges; run the collector from its own clone per A1.1, and never copy the PR's Makefile over this checkout's P1 Makefile (A1.6). |
| `error: required executable is unavailable: docker` | The Docker CLI is missing from that shell's PATH (workstation.md Stage 2); the collector never installs anything. |
| `error: Docker context: ...` (context not found or inspect failed) | The context named in DOCKER_CONTEXT does not exist on this machine; run `docker context ls` and pass an existing local context explicitly (A1.2). |
| `error: ENV=lab requires an explicitly selected local Docker endpoint` | The selected DOCKER_CONTEXT resolves to a remote ssh/tcp endpoint; point ENV=lab only at a local Unix/named-pipe context, never at a source or production engine (A1.2). |
| `error: no inventory artifact exists for the requested ENV` | Nothing was collected under that PLATFORM_ARTIFACT_ROOT yet, or it points at the wrong directory; run the collect step first and check `ls "$PLATFORM_ARTIFACT_ROOT"/*/inventory.json`. |
| `error: inventory ENV does not match the requested ENV` | The selected INVENTORY_FILE was collected under a different environment; revalidate with the matching ENV or the correct file. |
| `error: inventory schema rejected <path>: additional properties` | The artifact was hand-edited into a shape the pinned schema refuses (the validator never echoes rejected values); re-collect instead of editing the artifact in place. |
| `error: private inventory artifact could not be written` | The artifact root is not writable or exists as a file; recreate it per A1.2 and rerun. |
| `error: Docker stats: docker exceeded the inventory timeout` | Large fleet on the selected context; the collector marks resource usage `partial` or `unavailable`, records a collection issue, and stays blocked; a quieter daemon fits the timeout better. |
| VM tier green but you changed branch heads | Re-run the whole VM tier from the new head; evidence binds to the tested commit recorded in the manifest. |
