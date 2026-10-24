# AniTrend private platform migration

Status: implementation contract proposed for review. Baseline: [`e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3`](https://github.com/AniTrend/local-stack/commit/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3), reviewed 2026-10-24 UTC. This plan describes work to implement; it does not claim the target platform or validation commands already exist.

The goal is to provision, update, inspect and recover AniTrend's private platform through versioned infrastructure, CI and Dokploy without routine interactive SSH. The target is Pulumi TypeScript with the existing Hetzner Cloud provider, a small Ansible host baseline, Dokploy and Tailscale. Preserve APISIX initially. Doco-CD remains only on the old host during migration and loses ownership after successful cutover.

## Read in this order

1. [Current repository state and inventory gaps](current-state.md).
2. [ADR 0001: platform ownership and defaults](adr-0001-platform-ownership.md).
3. [Validation tiers and command contract](validation.md).
4. [Migration, recovery and rollback runbook](migration-runbook.md).
5. [Agent execution contract](agent-execution.md).
6. [Primary references](sources.md) and [machine-readable work graph](work-items.json).

These repository documents are the source of truth for implementation. The earlier research discussion is background, not a required input. Issues record work scope and acceptance; they link to this plan and each other. Before changing a decision, update the relevant ADR and affected acceptance criteria in the same reviewed change.

The plan's initial publication is a documentation PR. Implementation can branch from its documented commit while it follows the existing repository review process. Until a service's ownership handoff, the current [AGENTS.md](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/AGENTS.md), service source files and [Swarm runbook](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/stacks/README.md) remain authoritative for operating that service. Do not deploy unresolved generated stack files or silently apply target conventions to the old host.

## Phases and dependencies

Parent tracker: [#652](https://github.com/AniTrend/local-stack/issues/652). Documentation PR: [#651](https://github.com/AniTrend/local-stack/pull/651).

| Work ID | Phase | Issue | Prerequisites |
|---|---|---|---|
| P0-01 | 0: Inventory and constraints | [#653: reconcile the live inventory and migration constraints](https://github.com/AniTrend/local-stack/issues/653) | None |
| P1-01 | 1: Local lab and infrastructure | [#654: add an isolated Docker lab and validation contract](https://github.com/AniTrend/local-stack/issues/654) | None |
| P1-02 | 1: Local lab and infrastructure | [#655: add Pulumi Hetzner provisioning and protected state](https://github.com/AniTrend/local-stack/issues/655) | [P1-01 / #654](https://github.com/AniTrend/local-stack/issues/654) |
| P1-03 | 1: Local lab and infrastructure | [#656: add an idempotent host baseline with container and VM tests](https://github.com/AniTrend/local-stack/issues/656) | [P1-01 / #654](https://github.com/AniTrend/local-stack/issues/654), [P1-02 / #655](https://github.com/AniTrend/local-stack/issues/655) |
| P2-01 | 2: Dokploy platform integration | [#657: bootstrap Dokploy and reconcile its service registry](https://github.com/AniTrend/local-stack/issues/657) | [P1-02 / #655](https://github.com/AniTrend/local-stack/issues/655), [P1-03 / #656](https://github.com/AniTrend/local-stack/issues/656) |
| P2-02 | 2: Dokploy platform integration | [#658: isolate administration behind Tailscale and test ingress boundaries](https://github.com/AniTrend/local-stack/issues/658) | [P1-02 / #655](https://github.com/AniTrend/local-stack/issues/655), [P1-03 / #656](https://github.com/AniTrend/local-stack/issues/656), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657) |
| P2-03 | 2: Dokploy platform integration | [#659: deliver SOPS secrets to Dokploy without leaking deployment artifacts](https://github.com/AniTrend/local-stack/issues/659) | [P1-01 / #654](https://github.com/AniTrend/local-stack/issues/654), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657), [P2-02 / #658](https://github.com/AniTrend/local-stack/issues/658) |
| P2-04 | 2: Dokploy platform integration | [#660: adapt service sources into reproducible Dokploy deployment units](https://github.com/AniTrend/local-stack/issues/660) | [P0-01 / #653](https://github.com/AniTrend/local-stack/issues/653), [P1-01 / #654](https://github.com/AniTrend/local-stack/issues/654), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657), [P2-02 / #658](https://github.com/AniTrend/local-stack/issues/658), [P2-03 / #659](https://github.com/AniTrend/local-stack/issues/659) |
| P3-01 | 3: Delivery and recovery | [#661: promote verified releases through the private Dokploy API](https://github.com/AniTrend/local-stack/issues/661) | [P1-02 / #655](https://github.com/AniTrend/local-stack/issues/655), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657), [P2-02 / #658](https://github.com/AniTrend/local-stack/issues/658), [P2-03 / #659](https://github.com/AniTrend/local-stack/issues/659), [P2-04 / #660](https://github.com/AniTrend/local-stack/issues/660) |
| P3-02 | 3: Delivery and recovery | [#662: implement off-host backups and prove cold restoration](https://github.com/AniTrend/local-stack/issues/662) | [P0-01 / #653](https://github.com/AniTrend/local-stack/issues/653), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657), [P2-03 / #659](https://github.com/AniTrend/local-stack/issues/659), [P2-04 / #660](https://github.com/AniTrend/local-stack/issues/660) |
| P3-03 | 3: Delivery and recovery | [#663: verify service health resource budgets and deployment observability](https://github.com/AniTrend/local-stack/issues/663) | [P0-01 / #653](https://github.com/AniTrend/local-stack/issues/653), [P2-02 / #658](https://github.com/AniTrend/local-stack/issues/658), [P2-04 / #660](https://github.com/AniTrend/local-stack/issues/660), [P3-01 / #661](https://github.com/AniTrend/local-stack/issues/661) |
| P4-01 | 4: Hetzner rehearsal | [#664: rehearse provisioning deployment restore and rollback on Hetzner](https://github.com/AniTrend/local-stack/issues/664) | [P0-01 / #653](https://github.com/AniTrend/local-stack/issues/653), [P1-01 / #654](https://github.com/AniTrend/local-stack/issues/654), [P1-02 / #655](https://github.com/AniTrend/local-stack/issues/655), [P1-03 / #656](https://github.com/AniTrend/local-stack/issues/656), [P2-01 / #657](https://github.com/AniTrend/local-stack/issues/657), [P2-02 / #658](https://github.com/AniTrend/local-stack/issues/658), [P2-03 / #659](https://github.com/AniTrend/local-stack/issues/659), [P2-04 / #660](https://github.com/AniTrend/local-stack/issues/660), [P3-01 / #661](https://github.com/AniTrend/local-stack/issues/661), [P3-02 / #662](https://github.com/AniTrend/local-stack/issues/662), [P3-03 / #663](https://github.com/AniTrend/local-stack/issues/663) |
| P5-01 | 5: Production migration | [#665: provision the production target and validate an isolated canary](https://github.com/AniTrend/local-stack/issues/665) | [P4-01 / #664](https://github.com/AniTrend/local-stack/issues/664) |
| P5-02 | 5: Production migration | [#666: cut over services with writer fencing and data-safe recovery](https://github.com/AniTrend/local-stack/issues/666) | [P5-01 / #665](https://github.com/AniTrend/local-stack/issues/665) |
| P6-01 | 6: Retirement and handover | [#667: retire legacy deployment ownership and complete operations handover](https://github.com/AniTrend/local-stack/issues/667) | [P5-02 / #666](https://github.com/AniTrend/local-stack/issues/666) |
| P7-01 | 7: Optional gateway evaluation | [#668: evaluate APISIX standalone against Kong without blocking migration](https://github.com/AniTrend/local-stack/issues/668) (optional) | [P6-01 / #667](https://github.com/AniTrend/local-stack/issues/667) |

P0 inventory and the offline P1 lab can begin independently. P1 implementation and P2/P3 preparation can proceed with synthetic inputs where live access is unavailable. Production work cannot bypass the dependency graph. P7 is optional and is not a condition for completing the core migration.

Each issue contains its context, source paths, deliverables, commands, negative tests, completion evidence and rollback boundary. A closed prerequisite is necessary but not sufficient: its linked evidence must apply to the candidate commit and target environment.

## Required outcomes

- One documented deployment owner for every workload; a routine update has one entry point.
- Real local Docker validation of Pulumi resource lifecycle and container-compatible Ansible roles before cloud migration.
- A full Linux VM and disposable Hetzner rehearsal prove host services, firewalls, mounts, reboots, actual provider operations and recovery.
- Private dashboards/admin APIs remain inaccessible from the public internet, including requests with matching Host headers/TLS SNI.
- Application releases identify source commit, rendered configuration and image digests, and are promoted only after applicable checks.
- State is recoverable from off-host backups; the old host is retained through the documented rollback period.
- Existing local service Compose development remains available.
- Routine resource/service changes, secrets rotation, logs, compatible rollback and recovery have executable runbooks.

## Scope boundaries

This project is AniTrend's own platform, not a multi-tenant service for arbitrary customer workloads. No k3s/Flux, custom Hetzner provider, multi-node HA cluster, new secret manager or gateway replacement is required for the core migration.

A fresh target VM is the default; no in-place installation over the current Traefik/Swarm host. No database major upgrade is bundled with the move. Existing closed tickets are historical references and are not reopened by this plan.

Creating this plan and its issues authorizes planning, not cloud spend, production cutover or destructive retirement. A future execution uses the already-established session/repository authorization and configured environment gates. Prepare a concrete preview/runbook before requesting any genuinely missing authorization; do not repeatedly ask about already-authorized steps.

## Completion and ownership

The core epic is complete when P0 through P6 meet their acceptance criteria and the evidence index records current release, infrastructure state location, backup/restore proof, private access proof and residual retained resources. Do not include credentials or customer data in this public repository or its issues.

The machine-readable graph stores stable work IDs, GitHub issue links and prerequisite IDs. GitHub issue state remains the live progress record; the JSON file must not be used as a stale duplicate status tracker.
