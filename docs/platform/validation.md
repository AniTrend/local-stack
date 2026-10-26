# Validation tiers and command contract

All commands in this document are required interfaces to implement, not commands available at the reviewed baseline. A target that is not implemented must exit non-zero with a specific explanation. A missing prerequisite must never be converted into a successful production gate.

## Validation ladder

| Tier | What runs | What it proves | What it cannot prove |
|---|---|---|---|
| T0 static and mocks | Schema/lint/type checks, Pulumi mocks, API fixtures, release-policy tests | Intent, relationships, deterministic rendering and rejected inputs | Provider operations, Pulumi engine lifecycle hooks, real host/network behaviour |
| T1 local Docker | Actual @pulumi/docker preview/up/update/destroy, real containers/volumes, Molecule convergence | Local provider lifecycle, container-compatible roles, secret/rendering contracts, cleanup | hcloud API, block-device attachment, host kernel/systemd/firewall/reboot |
| T2 full Linux VM | Actual pinned Dokploy, SSH/systemd, mounts, firewall, Tailscale, reboot, app tests | Complete host lifecycle and real deployment/restore behaviour on a Linux guest | Hetzner-specific resource behaviour if the VM is local |
| T3 disposable Hetzner | Real hcloud program and complete T2 suite on matching architecture/OS | Provider lifecycle, cloud/host networking, fresh-host restore and cutover rehearsal | Actual production inventory, production DNS and live data correctness |
| T4 production canary/cutover | Approved concrete preview, isolated canary, fenced data move and client checks | The actual migrated service and data meet the contract | Future HA or scale beyond measured limits |

Local Docker is mandatory before host migration. T0 alone, a Pulumi preview alone, Ansible --check alone and a Dokploy deployment HTTP 200 are insufficient. Ansible check mode has module-dependent coverage; run real convergence and verify state. Record all skips and unsupported modules.

## Lab construction

Provide pinned tool versions and lockfiles. Doctor checks Docker Engine API reachability, selected context/endpoint, Compose, CPU architecture, disk/memory, supported Node/Pulumi/Python/Ansible versions and required plugins/collections. It prints no credential values. Do not silently install software globally, change the user's default Docker context or initialize Swarm on their existing daemon.

Use an explicit local context allowlist, unique run ID and resource labels. @pulumi/docker owns its fixture resources; Molecule owns different fixtures or consumes a clearly defined inventory. Never have both destroy the same resource. Publish lab ports on 127.0.0.1 and use dummy secrets. Test that unrelated containers/volumes remain after cleanup.

Container tests cover users/packages/files/directories/SSH configuration where supported, not host-kernel administration. Host firewall, disk formatting, systemd, Tailscale routing, Docker installation and reboot checks belong to T2. Use a disposable full Ubuntu 24.04 LTS VM by default, with an explicitly selected local hypervisor or the authorized disposable rehearsal host. Record image identity, architecture and provider. Containers with systemd or nested Docker can supplement tests but do not replace this host proof.

The user's macOS arm64 lab and Linux CI must be supported as declared platforms. If an image only runs under emulation, record that and require native validation on the target architecture before production. The existing stackctl setup action supports x86_64 only; reuse it only where its actual contract applies.

## Required command interface

Implement targets in a root Makefile using small scripts under tools/platform; no additional task runner is required. ENV is explicit and defaults must never select production. State and resource IDs must match ENV. The first argument validation occurs before any network mutation.

| Target family | Required result |
|---|---|
| platform-doctor | Prerequisite/context report; nonzero if blocked |
| platform-inventory / platform-inventory-validate | Read-only sanitized observation / schema validation |
| platform-lab-up / platform-lab-test / platform-lab-down | Create, verify and remove only T1-owned resources |
| platform-pulumi-test / platform-preview | Intent tests / selected provider preview with replacement analysis |
| platform-ansible-test / platform-host-verify | Container convergence / full VM host checks |
| platform-dokploy-test / platform-registry-check | Adapter contract and actual pinned instance validation |
| platform-network-test | Positive and negative reachability assertions |
| platform-secrets-test / platform-artifact-scan | Injection/rotation/failure cleanup / canary-secret scanning |
| platform-render / platform-compose-test / platform-release-verify | Deterministic bundle, runtime semantics and exact release identity |
| platform-ci-contract-test / platform-promote-test | Risk/identity/concurrency failure tests and real fixture promotion |
| platform-backup-test / platform-restore-test | Consistent backup and fresh-target integrity/recovery proof |
| platform-smoke / platform-observability-test | Application contracts and deliberate failure detection |
| platform-rehearse | T3 orchestration including T2, data recovery and cutover rehearsal |
| platform-canary / platform-cutover-preflight / platform-cutover | Production-only guarded stages from the concrete manifest |
| platform-ownership-check / platform-ops-verify | No competing controllers and routine operational exercises |
| platform-evidence-validate | Verify schema, completeness, redaction and applicable gates |
| platform-validate | Aggregate implemented T0/T1 suites; full local acceptance after P1-P3 |
| platform-gateway-contract-test | Optional P7 compatibility experiments |

Examples of the required completed interface:

```sh
make platform-doctor ENV=lab
make platform-lab-up ENV=lab
make platform-lab-test ENV=lab
make platform-pulumi-test ENV=lab
make platform-ansible-test ENV=lab
make platform-lab-down ENV=lab
make platform-host-verify ENV=lab TIER=vm
make platform-rehearse ENV=rehearsal
```

Each targeted command must run its meaningful assertions rather than merely echo a successful plan. Early issues run their own targets; the aggregate platform-validate is not used to claim later components exist. Run actual production mutation targets only under the runbook's applicable authorization.

## Ansible execution and prerequisites

`make platform-ansible-test ENV=lab` requires an explicit `PLATFORM_DOCKER_CONTEXT` selected from `PLATFORM_ALLOWED_DOCKER_CONTEXTS`. It accepts only a local Unix-socket Docker endpoint with Swarm inactive, and never changes the active Docker context. The runner builds a test-only Ubuntu 24.04 image from the pinned manifest digest using host networking only for the image build; the Molecule container runs on Docker's ordinary isolated bridge with no published ports. Each fixture gets a run-scoped name and owner/run labels. Before Molecule's initial destroy, the runner inspects that exact name and blocks if its ownership or run labels do not match. The scenario runs syntax validation, convergence, idempotence, injected drift, corrective convergence, verification and owned-container cleanup. The local image remains as a reusable cache.

`make platform-host-verify ENV=lab TIER=vm` requires an externally provisioned native Ubuntu 24.04 VM, a versioned lab-VM inventory, a signed host-trust bundle, an independently sourced Ed25519 trust root, bootstrap and automation SSH keys, a scoped Tailscale auth key and an approved `PLATFORM_TAILSCALE_TAG`. Required inputs use `PLATFORM_VM_INVENTORY`, `PLATFORM_VM_TRUST_BUNDLE`, `PLATFORM_VM_TRUST_ROOT`, `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY`, `PLATFORM_VM_AUTOMATION_PUBLIC_KEY`, `PLATFORM_VM_AUTOMATION_PRIVATE_KEY`, `PLATFORM_TAILSCALE_AUTH_KEY` and `PLATFORM_TAILSCALE_TAG`. Missing inputs produce blocked evidence, never a pass.

The runner validates inventory and SSH trust before connecting, then creates the dedicated automation account through the bootstrap account. Its `authorized_keys` file is exclusively managed to contain the declared Ed25519 key; recovery access remains with the bootstrap account. It proves a new SSH reconnect before applying host firewall rules.
The host verification sequence rejects a path-traversing storage identifier before device inspection, then converges the OS, declared storage, Tailscale and host firewall without installing Docker, Dokploy or Swarm. The storage role verifies an existing mount's device identity before creating the mount directory and preserves the filesystem root's owner and mode.
The VM scenario checks populated loopback data and metadata preservation, refuses unapproved formatting, tests the explicit create-only path on a blank loopback device, verifies Docker `DOCKER-USER` rules, reboots, verifies SSH/Tailscale/mount recovery and requires a zero-change second converge. A create-only volume additionally requires `PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT=I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES`.

The host command writes a non-secret `manifest.json` under `.artifacts/platform/<run-id>/` and removes its temporary generated Ansible inventory and `known_hosts` file after the run. The full VM command is not part of ordinary CI and never provisions HCloud resources.



## Shared schema contracts

The implementation must publish versioned JSON schemas and fixtures for these contracts:

1. Environment intent: schema version, environment, provider, project identity, region, OS image/version, architecture, server sizing, networks/CIDRs, volume definitions, public/private routes, allowed Docker context, credential references, state backend reference and safety policy.
2. Host inventory: the HCloud Pulumi v1 contract in `infra/pulumi/shared/pulumi-inventory.schema.json` and the versioned external lab-VM variant in `infra/pulumi/shared/lab-vm-inventory.schema.json` support rehearsal/production and `ENV=lab TIER=vm` respectively. Both variants carry exact environment, host identity reference, volume identifiers and mount paths. Mount paths are non-overlapping descendants of `/srv`, `/mnt` or `/var/lib`.
   The lab-VM volume schema requires `format_policy: never` or `format_policy: create-only`; create-only requires `data_classification: empty` and a separate command confirmation. HCloud inventory v1 is normalized by the adapter to `format_policy: never`. The SSH trust record in `infra/pulumi/shared/ssh-host-trust.schema.json` is signed and verified against an independently supplied trust root. The adapter rejects non-ready inventory and mismatched signatures, identities, addresses or route sources before writing SSH settings. Inventory and trust contain no private keys.
3. Service catalog: stable logical ID, source paths, runtime mode, Dokploy IDs, deployment owner, dependencies, image digest/platform, network aliases, ingress classification, health contract, secrets references, mounts/data classification and recovery method.
4. Release record: source commit, normalized bundle/config hash, image digest map, schema versions, target environment, verification run ID, promotion identity and prior release.
5. Evidence manifest: schema version, candidate commit, environment, tier, tool/provider/image versions, architecture/native-or-emulated, timestamps, individual test result/artifact references, deployment IDs, backup references, cleanup and gate decision.

Unknown fields may be allowed for forward compatibility only if safety-critical validation remains strict. Missing environment, identities or required secret references must fail closed. A schema migration must update adapters and tests together.

## Minimum meaningful assertions

- Pulumi: actual resources exist; second identical apply is a no-op; controlled change is visible; owned cleanup works; production deletion/replacement protection is enforced at the applicable tier.
- Ansible: actual state matches assertions; second converge has zero unexplained changes; injected drift is corrected; SSH and Tailscale reconnect after reboot; mounts persist; stable device identifiers must be direct children of `/dev/disk/by-id`; an existing mount's device and filesystem-root metadata are preserved; known filesystem signatures and existing data are preserved; formatting requires an explicit empty-device create-only policy and confirmation.
- Dokploy: retries do not duplicate resources; deployed digest/config match the requested immutable release; terminal status plus readiness is required; controller outage does not stop running apps.
- Secrets: dummy canary reaches only intended service; failed/missing/rotated values behave correctly; successful, failed and interrupted runs leave no unauthorized plaintext or leaked artifacts.
- Networking: outside-tailnet public IPv4/IPv6 and direct-port probes with private Host/SNI fail; authorized access works; unauthorized tailnet/private-network access fails; public client contracts and renewal work.
- Data: seeded records/uploads/roles/gateway configuration survive redeploy and cold restore; consistent backup identity and measured RPO/RTO are recorded.
- CI: wrong commit/environment/digest, failed checks, untrusted PR, malformed model output, replayed/stale jobs and concurrent mutations cannot promote.
- Migration: source writers are fenced; pre-write rollback works; after target writes, blind stale-source rollback is rejected and the tested recovery procedure preserves data.

## Evidence and gate semantics

Write only non-secret evidence to ignored .artifacts/platform/<run-id>/. The canonical record is manifest.json plus named assertion reports and exact commands/exit codes. Restrict CI artifact access/retention where reports reveal internal topology. Put secret-bearing data and production backup contents in approved encrypted storage; publish only opaque references.

Allowed result states are pass, fail, blocked and skipped. A required blocked/skipped test prevents its gate passing. If a test is inapplicable, record the reason and the approved applicability rule. Never convert 'not run' to pass. Runtime artifacts must identify the tested commit and actual versions; material changes invalidate affected results.

Gate G0: inventory/constraints complete. G1: applicable T0/T1 work complete. G2: real Dokploy/Linux VM/secret/network/data/CI/ops contracts pass. G3: real Hetzner rehearsal, fresh restore, rollback and 24-hour soak pass. G4: production target/canary and concrete cutover manifest pass. G5: fenced cutover and 24-hour acceptance soak pass. G6: 7-day retention, post-cutover recovery verification and ownership handover complete.

A G2 Linux VM may be the authorized rehearsal VM, but G3 cannot pass until both its provider checks and all G2 checks pass. Ordinary PR CI never provisions paid cloud resources. Resumable scheduled verification may cover soak periods; no agent should wait in a blocking shell sleep for hours.
