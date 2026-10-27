# Migration execution and handover runbook (P4 through P6)

Status: operator procedures for stages that are planned and gated, not executed. This document authorizes nothing by itself. Cloud spend, production mutation and destructive retirement require the explicit approvals named in each stage. Every numeric value below is either a planning target quoted from `docs/platform` or a field the platform owner must set before execution; none is a measured promise.

Scope: first-time execution of the rehearsal stage (P4-01, issue #664), the production canary stage (P5-01, issue #665), the fenced cutover stage (P5-02, issue #666), and retirement plus operations handover (P6-01, issue #667), with the boundary of the optional gateway evaluation (P7-01, issue #668). Phases P0 through P3 and their contracts are prerequisites described in the gate matrix, not re-derived here.

Canonical contracts this runbook implements (read before acting, they are the source of truth):

- [Platform plan entry point](../README.md)
- [ADR 0001: platform ownership and defaults](../adr-0001-platform-ownership.md)
- [Validation tiers and gate semantics](../validation.md)
- [Migration recovery and cutover contract](../migration-runbook.md)
- [Current state and inventory boundary](../current-state.md)
- [Agent execution contract](../agent-execution.md)
- [Primary references](../sources.md) and [machine-readable work graph](../work-items.json)

Sibling runbooks this document links to (created alongside this file by the same documentation change):

- [Workstation and access setup](workstation.md): initial workstation build, account inventory, credential recovery starting points. Do this first if you have no working environment or no independent account access.
- [Inventory and host runbook](inventory-and-host.md): how live host facts are reconciled and where the P0 live inventory lands.
- [Delivery and recovery runbook](delivery.md): release promotion, restore workflows and routine operations detail that stages here call into.

If any linked runbook is absent at your commit, treat the related step as blocked, not optional. Report the missing prerequisite and stop that stage.

## 1. How to use this runbook

1. Work only on one stage at a time. A stage is *ready* only when: every gate in its prerequisite row of the gate matrix has passed evidence for the exact candidate commit; the input fields in section 6 are filled from real observations; the named authorization exists as a recorded explicit approval (an explicit session authorization, configured repository environment protection, or an approved change record); and the command interfaces the stage needs are implemented (section 3). Anything else is a stop, not a workaround.
2. Every command block carries three labels: where it runs, its mutation scope, and what it requires. Run nothing outside those labels. Commands shown for unimplemented interfaces are specifications, they cannot be run until their implementing issue merges; the root Makefile fails closed with exit status 2 for unknown targets, which is the intended behaviour.
3. Record evidence as you go using the template in section 13. Evidence lives in the ignored `.artifacts/platform/<run-id>/` directory locally and secret-bearing material goes only into the owner's separately restricted storage (opaque references only, never raw dumps, keys or backup contents in the repository or issues).
4. Stop conditions are listed inline and summarized in section 15. When you stop, preserve evidence, name the exact blocker, and hand off. An unavailable prerequisite is a blocker report, never a pass.

## 2. Glossary

| Term | Meaning in this runbook |
|---|---|
| Source | The existing host (and its controllers: Doco-CD, Portainer, the legacy deployer runner) that currently serves live traffic and holds live data. It stays authoritative until the cutover gate records otherwise. |
| Target | A freshly provisioned host running the new platform stack (Pulumi hcloud, Ansible baseline, Dokploy). Rehearsal targets are disposable; the production target becomes the source's successor only at cutover. |
| Writer | Any process that can mutate durable state: application write paths, database services, background workers, scheduled jobs, webhook receivers, upload handlers, gateway configuration writes, Dokploy deployment actions. |
| Fence | Make a writer incapable of resuming unexpectedly: stop it, disable its trigger (timer, webhook, token, polling), and record the proof. Fencing is per service and must be rehearsed; generic commands are not fencing. |
| Quiesce | Fence writers, drain in-flight work and connections, and reach a recorded consistency point. |
| Consistency point | The exact source backup identity and timestamp after which the source accepted no writes. The boundary of the zero-write-loss guarantee. |
| First write | The first acknowledged write the target accepts after routing or connections switch. The moment the safe rollback class changes. |
| Canary | A target deployment using test hostnames and synthetic or explicitly isolated data, with all external side effects disabled. |
| Soak | A 24-hour (rehearsal and acceptance default) observation window made of resumable check batches, not a single sleeping process. |
| RPO / RTO | Recovery point objective (maximum acceptable data loss window) and recovery time objective (maximum acceptable restore duration). Planning targets: RPO no worse than 24 hours, cold-restore RTO no worse than 60 minutes; measured values must be recorded, not assumed. |
| Gate | A named validation gate (G0 through G6) in [validation.md](../validation.md). A gate passes only on evidence generated for the candidate commit and target environment; closing a GitHub issue is not evidence. |
| Cutover manifest | The immutable, fact-complete record defined in section 8.6 that makes cutover executable and auditable. |
| Forward repair | After target writes: keep the target as authority and fix the defect forward, following the rehearsed procedure. |
| Copy-back | After target writes: export target-side changes since the consistency point, replay them into a validated source restore, verify consistency, then deliberately choose which side resumes authority. DNS is never the deciding mechanism. |
| Copyback prerequisites | Change capture on the target (database log/audit/export or application ledger), a rehearsed reconciliation script, verification queries, and a recorded acceptance procedure. Required before cutover day; unrehearsed reconciliation is not a rollback option. |
| Retention window | The 7-day minimum after cutover during which the source host stays stopped and fenced and independently recoverable backups exist. |

## 3. Implementation status and the fail-closed rule

At the branch this runbook was written from (`feat/platform-ansible-656`), the root Makefile implements exactly these targets: `platform-doctor`, `platform-lab-up`, `platform-lab-test`, `platform-lab-down`, `platform-pulumi-test`, `platform-preview` (non-mutating preview for `ENV=lab|rehearsal|production`; hcloud previews require the approved Pulumi Cloud state backend), `platform-ansible-test` (container tier), `platform-host-verify` (requires `ENV=lab TIER=vm`), and `platform-evidence-validate` in its lab-only form: it requires `ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_40_HEX_SHA`, validates existing lab-run.v1 or host-verify.v1 evidence (schema, identity, every required assertion, zero-change counts, cleanup, recognizable secret markers), exits 2 on nonpassing, incomplete, mismatched or unknown later schemas, and its output is explicitly scoped to `docker-lab-lifecycle` or `host-baseline`; it never approves G0 through G6 gates, evidence authenticity or the current runtime, and it does not implement any future deployment command. Every other platform target exits with status 2 and a specific explanation.

Verify before any stage:

```sh
# Run from: operator workstation, repo checkout. Mutation: none.
make -n platform-rehearse ENV=rehearsal 2>&1
```

If the output contains `No rule for target`, that interface is not implemented at your checkout. The owning issue (from [work-items.json](../work-items.json)) is still open; the stage that needs it is blocked. Never substitute a hand-rolled equivalent for a specified mutating interface.

| Interface group | Status at writing | Owning work |
|---|---|---|
| T0/T1 lab, preview, Ansible container and VM-verify commands | Implemented | #654, #655, #656 |
| Lab evidence validation (`platform-evidence-validate ENV=lab TIER=docker|vm`) | Implemented (lab-run.v1 / host-verify.v1 evidence only; no gate approval) | Parent platform tooling |
| Inventory targets | Published separately in draft [PR #673](https://github.com/AniTrend/local-stack/pull/673), not integrated into this checkout; G0 remains blocked | #653; see [inventory and host](inventory-and-host.md#part-a-p0-01-live-inventory-reconciliation-653) |
| Dokploy adapter, network, secrets, render, release, CI promotion, backup, restore, smoke, observability targets | Specified, not implemented | #657 through #663 |
| Rehearsal orchestration (`platform-rehearse`), rehearsal restore/network/evidence targets | Specified, not implemented | #664 |
| Production guarded stages (`platform-canary`, `platform-cutover-preflight`, `platform-cutover`) | Specified, not implemented | #665, #666 |
| Ownership and operations checks (`platform-ownership-check`, `platform-ops-verify`), aggregate `platform-validate`, optional gateway tests | Specified, not implemented | #667, #668 |

Manual procedures that remain human work regardless of tooling: recorded explicit approvals, manifest completion, fencing decisions per store, the soak batch review, rollback decisions, and any step explicitly marked "manual" below.

## 4. Numeric targets and owner-set values

Planning targets quoted from [migration-runbook.md](../migration-runbook.md) (targets to measure, not promises):

| Value | Planning default | Note |
|---|---|---|
| Backup RPO | no worse than 24 hours | P0 must set and justify any different target. |
| Cold-restore RTO | no worse than 60 minutes | Measured during rehearsal and restore tests. |
| Acknowledged write loss at cutover | zero | The quiesced cutover must lose zero acknowledged writes. |
| Soak duration | 24 hours | Rehearsal and post-cutover acceptance default. |
| Legacy retention | at least 7 days after cutover | Source host fenced and stopped; backups independently recoverable. |

Owner-set values (must exist in the cutover manifest before the window opens; the numbers below are only where each value is recorded, never defaults to copy):

| Field | Owner sets | Recorded in |
|---|---|---|
| Abort thresholds | Auth/API/flag failure rate, data-integrity discrepancy count, sustained error/latency regression, private exposure events, storage/resource exhaustion limits, minimum remaining maintenance time | Manifest, section 8.6 |
| Maximum maintenance duration | Absolute deadline for the cutover window | Manifest |
| Maintenance window | Calendar slot, attendees, secondary operator on call | Manifest |
| Spend cap and approval scope | Rehearsal and production budget ceilings and who approved them | Sections 7.2 and 8 |
| DNS TTL plan | Pre-cutover TTL, when it is lowered, convergence calculation | Manifest |
| Soak cadence | Batch interval for the 24-hour soak and who reviews batches | Manifest and section 9.6 |

If an owner refuses or defers setting a value, the stage that needs it is blocked. Never proceed on an assumed number.

## 5. Gate and evidence matrix

Gate definitions are canonical in [validation.md](../validation.md). The matrix below is the practical checklist: a stage may start only when every predecessor row shows evidence that applies to the candidate commit and target environment. Read each prerequisite issue for its current evidence; closed-without-evidence is not a pass.

| Gate | Work items | Evidence that must exist (summary) | Required command interfaces (see section 3 for status) |
|---|---|---|---|
| G0 inventory and constraints complete | #653 | Live inventory reconciled against the actual host; constraints and RPO/RTO owner-set; synthetic values visibly marked | `make platform-inventory ENV=lab`, `make platform-inventory-validate ENV=lab` |
| G1 local lab and infrastructure (T0/T1) | #654, #655, #656 (container-tier parts) | Real local Docker provider lifecycle, Molecule container convergence, Pulumi intent tests with a second-apply no-op, deterministic preview | `make platform-doctor ENV=lab`, `make platform-lab-up ENV=lab`, `make platform-lab-test ENV=lab`, `make platform-lab-down ENV=lab`, `make platform-pulumi-test ENV=lab`, `make platform-preview ENV=lab`, `make platform-ansible-test ENV=lab` |
| G2 platform integration and delivery | #656 (VM-tier part), #657, #658, #659, #660, #661, #662, #663 | Linux VM host checks with real SSH/Tailscale/mount/firewall/reboot recovery; pinned Dokploy bootstrap and registry reconciliation; private network boundary proofs; secret injection and artifact scans; rendered bundles with release identity; promotion through the private API with negative tests; consistent off-host backups with a cold fresh-VM restore; health/budget/observability checks | `make platform-host-verify ENV=lab TIER=vm`, `make platform-dokploy-test ENV=lab`, `make platform-registry-check ENV=lab TIER=vm`, `make platform-network-test ENV=lab TIER=vm`, `make platform-secrets-test ENV=lab`, `make platform-artifact-scan ENV=lab`, `make platform-render ENV=lab`, `make platform-compose-test ENV=lab`, `make platform-release-verify ENV=lab`, `make platform-ci-contract-test ENV=lab`, `make platform-promote-test ENV=lab TIER=vm`, `make platform-backup-test ENV=lab`, `make platform-restore-test ENV=lab TIER=vm`, `make platform-smoke ENV=lab TIER=vm`, `make platform-observability-test ENV=lab TIER=vm` |
| G3 rehearsal complete | #664 | This runbook's section 7 executed end to end: provision, baseline, deploy, restore, failure injection, both rollback classes, 24-hour resumable soak, cleanup orphans checked; decision record with measured timings | `make platform-rehearse ENV=rehearsal`, `make platform-restore-test ENV=rehearsal`, `make platform-network-test ENV=rehearsal`, `make platform-evidence-validate ENV=rehearsal` |
| G4 production target and canary | #665 | Approved concrete production preview applied to a fresh target; isolated canary verified; cutover manifest complete with no unresolved field | `make platform-preview ENV=production`, `make platform-canary ENV=production`, `make platform-evidence-validate ENV=production` |
| G5 cutover and acceptance soak | #666 | Preflight clean, source frozen and fenced, final consistent backup recorded, zero acknowledged write loss, target writers enabled after checks, 24-hour acceptance soak passed | `make platform-cutover-preflight ENV=production`, `make platform-cutover ENV=production`, `make platform-smoke ENV=production`, `make platform-evidence-validate ENV=production` |
| G6 retirement and handover | #667 | 7-day retention closed, post-cutover restore proven, ownership revoked with replacement access proven, routine operations demonstrated, destructive retirement separately approved and residual costs recorded | `make platform-ownership-check ENV=production`, `make platform-ops-verify ENV=production`, `make platform-validate ENV=lab` |
| Optional P7 | #668 | Gateway evaluation ADR with measured results; excluded from core completion | `make platform-gateway-contract-test ENV=lab` |

Note on the evidence validator: the implemented `platform-evidence-validate` validates only lab-tier evidence (`ENV=lab TIER=docker|vm` with manifest and commit arguments) against the lab-run.v1 or host-verify.v1 schemas, and its report is scoped to `docker-lab-lifecycle` or `host-baseline`. The `ENV=rehearsal` and `ENV=production` variants named in the G3, G4 and G5 rows remain specified interfaces from [work-items.json](../work-items.json); the lab validator does not implement them, and no validator output constitutes G0 through G6 gate approval, evidence authenticity or a statement about the current runtime.

Delegation checklist (who holds what at each stage):

| Task | Primary role | Backup and check |
|---|---|---|
| Approve scope, budget, maintenance window, thresholds, destructive retirement | Platform owner | Approval recorded through the applicable explicit channel with date and exact scope: an explicit session authorization, configured repository environment protection, or an approved change record |
| Gather site facts and inventory | Operator | Cross-check against [inventory-and-host.md](inventory-and-host.md) output and P0 live inventory |
| Hold credentials and recovery material | Owner, held in independent protected storage outside the target (canonical requirement) | A second independent holder is a recommended resilience measure; if adopted, record it in the manifest |
| Execute ready stages and record evidence | Operator | Secondary operator must be able to read the evidence and resume |
| Run the soak batches and review | CI scheduler plus operator review | Never one person sleeping through the window; batch evidence reviewed at agreed intervals |
| Decide abort/rollback | Operator on duty, bounded by owner-set thresholds | Escalate to owner for post-write reconciliation decisions (section 9.7) |
| External probes | Run from a vantage outside the target failure domain and outside the tailnet | Probe host identity and location recorded in evidence |

## 6. Stage 0: prepare inputs (always first)

Before each stage, obtain its preparation inputs, record who supplied them, and stop that stage until they exist. Site-specific values come from the live host and owner, never from this document or memory of a previous conversation. Outputs that can only exist during execution, such as the final quiesced backup identity and first target-write timestamp, are recorded in the execution ledger at their specified step, not invented as G4 prerequisites.

| Input | How to obtain | Who authorizes or supplies | Check and stop condition |
|---|---|---|---|
| Candidate release commit and infrastructure commit | Owner chooses the release under review; record both SHAs | Owner | Stop if the two commits have no passing applicable evidence yet |
| Confirmed Hetzner project, location and billing entity | Hetzner console (Cloud console, project list) or owner statement; verify by reading, not by guessing | Owner | Stop if the project identity or location is ambiguous; ambiguous target identity is a hard stop condition |
| Target architecture and server sizing | From the live host (`uname -m`, memory/disk) and P0 inventory; match production architecture in rehearsal | Owner confirms | Stop if the live architecture contradicts the plan |
| OS image identity (Ubuntu 24.04 LTS) | Hetzner console image list; record the exact image name and ID | Operator records, owner confirms | Stop if the pinned image is unavailable in the chosen location |
| DNS zone, records and TTLs | DNS provider admin UI or API: record zone, each public record name, type, value, current TTL; screenshot or export stored in restricted storage | Owner owns the zone | Stop if zone ownership or any record mapping is unclear |
| Private access plan | Tailnet identity and grants from the owner; the planned private hostname and certificate approach from P0 | Owner | Stop if tailnet admin access or an approved tag cannot be arranged |
| Backup destination and credentials | Owner statement plus a connectivity check during rehearsal; destination must be off-host and independently accessible | Owner | Stop if the destination is unreachable or its credentials can only be recovered from the failed target |
| Recovery credentials references | Age (SOPS) recovery location, SSH bootstrap and automation key locations, Pulumi access scope: opaque references only | Owner | Stop if critical material is not independently recoverable from protected storage outside the target; additional protected copies or holders are recommendations, not mandatory extra gates |
| Pulumi backend scope | Approved backend reference for rehearsal and production state | Owner | Stop if production state would live only on the host being replaced |
| Maintenance window, spend caps, thresholds | Owner decision with the approved numbers recorded | Owner | Stop if a preparation input in section 8.6 has no approved value or an execution-result field lacks a defined collection step |
| External probe vantage | Any host you control outside the tailnet and outside the target's failure domain; record its location | Operator arranges | Stop if probes would run from the tailnet itself |

Workstation and account setup (tools, accounts, credential recovery from independent storage) is documented in [workstation.md](workstation.md). Live host reconciliation is documented in [inventory-and-host.md](inventory-and-host.md). Do not continue until workstation tooling is in place and you can reach the owner.

## 7. Stage: Hetzner rehearsal (P4-01, issue #664, gate G3)

Authorization: recorded explicit approval from the platform owner for a bounded rehearsal budget in a dedicated project (an explicit session authorization, repository environment protection, or an approved change record). Rehearsal resources are disposable and isolated; they must not touch production.

### 7.1 Prerequisites checklist

1. All G0 through G2 rows in the gate matrix show evidence for the candidate commit (read the prerequisite issues and their evidence; do not trust closure alone).
2. Approved dedicated rehearsal project/credentials or an equivalently isolated policy, with its own names, DNS, state and budget (issue #664 requirement).
3. Section 6 inputs collected; production records and DNS untouched so far.
4. The four required rehearsal interfaces implemented (verify with the `make -n` check in section 3).

### 7.2 Concrete resource inventory, cost capture and spending approval

Plan the following inventory, then capture real prices from the Hetzner console or the `hcloud` CLI before requesting approval. Hetzner bills servers hourly with a monthly cap and continues billing a powered-off server until the resource is deleted; deletion is what stops charges (Hetzner billing FAQ, https://docs.hetzner.com/cloud/billing/faq). Volumes and snapshots likewise bill until deleted, so the budget must include the full lifetime including cleanup.

| Resource | Planning candidate (confirm against production sizing from P0) | Cost field to capture | Lifetime |
|---|---|---|---|
| Rehearsal server 1 (new target) | Same server type as the production intent, matching architecture; example candidate: CX-class 4 vCPU / 8 GB (owner confirms the production size) | Hourly rate and monthly cap from the console or `hcloud server-type describe` | Provision to destruction, including soak |
| Rehearsal server 2 (seeded old source) | Optional: only if the approved rehearsal scope includes a second disposable host. The default single-host scope runs the source side of the cutover rehearsal from an isolated synthetic old fixture (synthetic state and fixture services) on resources already in the table | Hourly rate and monthly cap (only when approved) | Needed only for the cutover rehearsal days |
| Volume for durable data rehearsal | 20 to 40 GB on the new target (mirror production volume plan) | Per-GB-month rate from the console | Same as server lifetime |
| Private network + cloud firewall | One network, one firewall; included | Zero direct cost; verify | Same as servers |
| Rehearsal DNS names | Owner-controlled zone or subdomain dedicated to rehearsal, records for public test names and private admin names, TTL 300 seconds for rehearsal (any short TTL is fine because no live traffic exists) | Zero cost | Remove at cleanup |
| Backup destination (rehearsal) | The owner-chosen off-host destination with the smallest sufficient tier | Provider price page | Through the rehearsal soak, then purged |
| Snapshots taken during rehearsal | As needed for the reboot/restore tests | Snapshot per-GB storage rate | Delete at cleanup, never auto-retain |

Spending approval procedure:

1. Fill the table above with captured real rates, compute a ceiling: `ceil = sum(hourly rate x maximum hours) + volume + backup destination + snapshots + 20% margin`. Maximum hours must include the 24-hour soak plus a 48-hour contingency.
2. Submit to the platform owner for recorded explicit approval with scope: project ID, resource types, ceiling, expiry date, and the statement that all resources are deleted (or explicitly retained with owner and expiry) by that date.
3. Record the approval reference in the rehearsal evidence. Provisioning without this record is a stop condition.
4. During the run, if projected spend approaches the ceiling, stop provisioning new resources and report. Never exceed the approved ceiling.

### 7.3 Isolation requirements (verify, do not assume)

- Separate Hetzner project or strictly scoped credentials, dedicated rehearsal state (never the production Pulumi stack), dedicated rehearsal DNS names, no production record changes.
- Verify before and after provisioning that the rehearsal program neither addresses nor imports production resources: read the preview resource list and confirm every resource name and ID is rehearsal-owned. Production resource IDs must not appear anywhere in rehearsal state.
- Rehearsal data is synthetic, or an explicitly permitted sanitized and encrypted copy, per issue #664. Never use production secrets, data or hosts in the rehearsal.

### 7.4 T2 and T3 orchestration

T2 (full Linux VM tier) proves the complete host lifecycle. The G2 VM may be the authorized rehearsal VM, but G3 cannot pass until both its provider checks and all G2 checks pass. Run T2 first on a disposable VM, then run the full suite again as part of T3 on the Hetzner rehearsal host.

T2 inputs (required, blocking): `PLATFORM_VM_INVENTORY`, `PLATFORM_VM_TRUST_BUNDLE`, `PLATFORM_VM_TRUST_ROOT`, `PLATFORM_VM_BOOTSTRAP_PRIVATE_KEY`, `PLATFORM_VM_AUTOMATION_PUBLIC_KEY`, `PLATFORM_VM_AUTOMATION_PRIVATE_KEY`, `PLATFORM_TAILSCALE_AUTH_KEY`, `PLATFORM_TAILSCALE_TAG`. Missing inputs produce blocked evidence, never a pass. Where each comes from is documented in [workstation.md](workstation.md) and [inventory-and-host.md](inventory-and-host.md).

T2 sequence (from the implemented contract):

```sh
# Run from: operator workstation, repo checkout. Mutation: local lab resources only.
# Requires: Docker daemon reachable via an explicitly allowed local context.
make platform-ansible-test ENV=lab
```

```sh
# Run from: operator workstation. Mutation: the declared disposable VM only.
# Requires: the eight PLATFORM_VM_* inputs above, a versioned lab-VM inventory and signed host-trust bundle.
make platform-host-verify ENV=lab TIER=vm
```

What T2 must show: automation account bootstrap over a verified SSH trust path, a proven SSH reconnect before firewall changes, OS/storage/Tailscale/firewall convergence with correct `DOCKER-USER` behaviour, reboot with SSH/Tailscale/mount recovery, and a zero-change second converge. A create-only volume additionally requires `PLATFORM_VM_ALLOW_CREATE_ONLY_FORMAT=I_UNDERSTAND_THIS_FORMATS_ONLY_DECLARED_EMPTY_VOLUMES`. Never format a device that might hold data.

T3 sequence (steps mirror issue #664; exact arguments come from the implemented orchestration target, never improvised):

1. Non-mutating preview first:

```sh
# Run from: operator workstation. Mutation: none (preview reads only).
# Requires: approved Pulumi Cloud state backend for the rehearsal stack; rehearsal credentials configured.
make platform-preview ENV=rehearsal
```

Check the preview: rehearsal-owned names only, expected resource set, no production IDs.

2. Provision and validate the rehearsal environment, then apply the validated Ansible baseline, bootstrap the pinned Dokploy version, verify the private network, inject test secrets, register services and promote a release from a clean checkout at the exact candidate commit. These are the responsibilities of `make platform-rehearse ENV=rehearsal` once implemented; before that target exists, the stage is blocked and the operator records blocked evidence instead of running manual equivalents.

3. Seed synthetic state and exercise, per issue #664: an application update and rollback, a fresh-host data restore (`make platform-restore-test ENV=rehearsal`), a controlled reboot with mount recovery, expired and missing credentials, denied public admin access, and a controller outage.

4. Run the network boundary suite from outside the tailnet (`make platform-network-test ENV=rehearsal`): public IPv4 and IPv6 probes with private Host/SNI must fail, direct ports must fail, unauthorized tailnet/private-network access must fail, authorized access must work, public client contracts and certificate renewal must work.

5. Rehearse the complete cutover path with the isolated synthetic old fixture (or the approved second disposable host) and the fresh target: writer fencing, final backup, traffic switch on rehearsal names, pre-write rollback, and a failure injected after target writes that demonstrates stale-source DNS rollback is rejected (section 9.7 mechanics, on synthetic data).

6. Run the 24-hour soak as resumable check batches (section 9.6 mechanics; cadence recorded in evidence; no blocking sleep).

7. Validate evidence with `make platform-evidence-validate ENV=rehearsal` once that variant is implemented (the currently implemented lab-only validator validates lab-run.v1 and host-verify.v1 evidence and does not cover rehearsal evidence; until the rehearsal variant lands, record blocked evidence for this step), then produce the decision record: exact versions/digests, measured downtime, RPO/RTO/headroom, unresolved blockers, cleanup results, and the validated site-specific procedures that section 9 consumes (freeze commands, fence commands per store, restore commands, probe commands).

### 7.5 Cleanup with exact identity verification

Destruction is allowed only for rehearsal-owned resources, only through their state, and only after identity verification. The rehearsal issue boundary: cancel only the disposable run, remove its owned resources using its state, keep evidence.

1. Collect the rehearsal run's state reference and list every resource with its ID, name, creation label and owner/run label.
2. Destroy through the orchestration path so state and reality stay consistent; then verify in the Hetzner console (or `hcloud` CLI) that each expected resource is gone by its exact ID: servers, volumes, network, firewall, SSH keys, snapshots, floating IPs if any, rehearsal DNS records.
3. Orphan check: search the rehearsal project for any remaining chargeable resource (including stopped servers, snapshots, backup objects). Hetzner keeps billing until deletion, so a forgotten snapshot is a real cost. Record the search command or console navigation, the result, and a zero-orphan confirmation. If something must be retained deliberately, record it with owner and expiry date in the evidence.
4. Confirm production resources were untouched: production IDs unchanged, production DNS unchanged. Include this statement in the decision record.

A rehearsal failure never authorizes changing the production host.

### 7.6 Rehearsal outputs

- Decision record (section 13 template) with measured values and every blocker.
- The validated, site-specific procedure set that the production stages consume: exact freeze and fence commands per store and controller, restore commands, probe commands, and the populated manifest skeleton (section 8.6) with rehearsal observations where production values are still pending.
- Explicit statement of what remains unimplemented or unproven; anything unresolved here blocks P5.

## 8. Stage: production target and isolated canary (P5-01, issue #665, gate G4)

Authorization: separate, explicit approval for the production environment scope: the concrete preview to be applied, the resource budget, and the fact that the old host remains untouched and serving. The canary stage must not change public traffic, mutate production data, or create duplicate background workers.

### 8.1 Prerequisites checklist

1. G3 evidence applies to the exact candidate commit (the passing rehearsal commit from section 7.6).
2. Recorded explicit approval for the production preview scope, resource budget, canary isolation plan, and manifest completion responsibility.
3. Current production backup exists and is independently restorable (the live source must not enter this stage without a usable backup).
4. All section 6 inputs still current; re-check drift between the P0 inventory, rehearsal observations and production immediately before cutover (section 8.7).

### 8.2 Concrete preview and provisioning

```sh
# Run from: operator workstation. Mutation: none (preview only).
# Requires: approved Pulumi Cloud production state backend; production credentials configured.
make platform-preview ENV=production
```

Record the preview output: exact resources to be created, replacement/deletion analysis (must show none against the live source; the fresh target must not import or replace production resources), cost estimate against the approved budget.

After approval: provision the fresh target, apply the validated baseline, bootstrap Dokploy and restore only approved configuration. The old host and its controllers stay intact and serving. The provisioning path is the implemented production flow behind `make platform-canary ENV=production` once that interface merges; until then the stage is blocked.

### 8.3 Canary isolation (the core of this stage)

Deploy canary services using synthetic or isolated restored data and test hostnames. Isolation is verified with tests and logs, not with an environment name. Complete this disablement matrix for every migrated service before any canary deployment; a service that cannot have an effect safely disabled stays off:

| Effect class | Disablement expectation | How verified |
|---|---|---|
| Background workers and consumers | Not started, or started against isolated queues only | Process list on target; queue isolation check |
| Scheduled jobs (cron/timers) | Disabled or pointed at isolated fixtures | Timer/unit listing evidence |
| Outbound webhooks and integrations | Endpoint list reviewed; calls disabled or intercepted to a collector | Egress log or collector evidence during the canary |
| Email and notifications | Suppressed globally for the canary | Provider console or suppressed-send evidence |
| Feature flag mutation | Admin writes disabled; SDK delivery unaffected or isolated | Admin API reject test |
| Writes to live stores | None: canary uses isolated stores; no shared live database, no shared live uploads | Store isolation listing; negative write probe from the canary to live stores must fail |
| Public DNS | Unchanged; canary reachable only via test hostnames | DNS record comparison before and after |

Prove the target cannot accidentally write to live stores or send real messages: run the negative write probe and the egress checks, and record both. A read-only UI does not imply the application is read-only.

### 8.4 Canary verification

Verify per issue #665: private access works from the authorized tailnet and fails from the public internet (rerun the boundary suite against the production target with test names), real public routing on test names, image architectures match the recorded native architecture, resource headroom matches the rehearsal decision record, backups run and are restorable in the production destination, restart recovery works, and every deployed digest matches the approved release record.

### 8.5 Preparing the cutover manifest (start early, finish completely)

Draft the manifest during this stage and finalize its preparation inputs before cutover. It is a dated, versioned document stored with platform evidence. Every preparation input needs a real value and an acquisition note; unresolved preparation inputs block G4. Record the currently restorable backup and approve the final-backup procedure now. The actual final backup identity, checksum, consistency point and first target-write timestamp are execution results collected later in sections 9.2 and 9.5. Bind that execution ledger to the approved manifest's content hash; do not invent future results or rewrite the approved plan to hide them. The owner records explicit approval through the applicable channel (session authorization, repository environment protection, or an approved change record). A plan change produces a new approved version and reruns affected checks.

### 8.6 Cutover manifest: required fields and how to obtain each

| Field | How to obtain |
|---|---|
| Candidate release commit, infra commit, verified evidence run IDs | From the rehearsal decision record and PR records; quote the exact SHAs |
| Old project/server/volume/network/firewall IDs | Hetzner console read of the live project; record every ID exactly; production resources must be protected from deletion (Pulumi protect semantics, source S06) per the infrastructure contract |
| New project/server/volume/network/firewall IDs | Read from the provisioned target created in section 8.2 |
| Stack/service IDs (source and target) | Source: from the live controller inventory during P0/rehearsal cross-check; target: from the provisioned Dokploy registry; never invent an ID |
| Current image digests and DB majors (source) | Live inspection of the source during the pre-cutover drift recheck; record digest per service and database major per store |
| Target image digests and DB majors | From the canary deployment record; must equal the approved release digests |
| DNS records and TTL plan | Owner zone export; record each record (name, type, value, current TTL), the planned pre-cutover TTL, when it was lowered, and the convergence calculation (section 9.4) |
| Private access and certificates | Tailnet grants reference, private hostnames, certificate issuance and renewal procedure from the canary verification |
| Workers, cron, webhooks, queues, email, external effects | The completed section 8.3 matrix, restated for cutover (what stays disabled on the target until section 9.5) |
| Every write path | From the live inventory: application write endpoints, database services, workers, upload handlers, gateway configuration writers, Dokploy deployment actions; each with its fence method and the rehearsed command or UI path |
| Freeze/resume commands | Validated during rehearsal against the equivalent controller/service; recorded verbatim; resume commands listed beside freeze commands |
| Restorable backup and final-backup procedure | Before G4: record an existing verified backup's identity/checksum, the approved final-backup destination and exact rehearsed commands. During section 9.2: append the actual final object identity, checksum and consistency timestamp to execution evidence linked to this approved manifest |
| Restore identities and procedure | The validated restore commands and their expected outputs from rehearsal |
| Recovery credentials references | Opaque references to age key holders, SSH bootstrap, tailnet admin, DNS admin; at least one independent protected storage location per critical material, outside the target (a second independent holder is a recommended resilience measure) |
| Maximum maintenance duration | Owner-set absolute deadline |
| Abort thresholds | Owner-set numbers for the section 9.7 table |
| Observed restore time | The measured fresh-restore duration from rehearsal/restore tests, recorded as the expectation for cutover validation |
| Selected pre-write and post-write recovery procedures | The two procedures from section 9.7, selected and rehearsed |
| First-write record fields | Section 9.5: what will be recorded when the target accepts its first write |
| Soak thresholds and cadence | Owner-set; section 9.6 |
| Contacts and handoff | Primary operator, secondary operator, owner, escalation path, and where evidence lives |

### 8.7 Immediate pre-cutover drift recheck

Before opening the maintenance window: re-collect targeted production inventory (image digests, DB majors, volumes, DNS records, worker lists, DNS TTLs) and compare against rehearsal and the manifest. Material changes invalidate only the affected gate and require that gate to rerun. Unexplained drift is a stop condition.

## 9. Stage: fenced cutover (P5-02, issue #666, gate G5)

Authorization: the approved cutover manifest (recorded explicit approval of its content) and the owner's approval of the specific maintenance window. Execute against the recorded host/resource identities only. Stop on unexpected drift, missing evidence, or a threshold breach (section 9.7).

### 9.1 Pre-flight (all must be true)

1. Approval scope, identities, release and available recovery time verified against the manifest; the source and target are unambiguously identified (ambiguous identity is a hard stop).
2. A fresh backup destination is ready and reachable; restore tooling and credentials available.
3. All fences are rehearsed and their commands recorded; secondary operator reachable.
4. `make platform-cutover-preflight ENV=production` is implemented and passes for the approved manifest. If it is missing, blocked or failing, stop before freezing production controllers or writers. The manual checklist above is preparation evidence only and cannot substitute for the required guard.

### 9.2 Freeze controllers and fence all write paths, then take the final consistent backup

Order matters: freeze first, then backup. A backup taken while any writer can still run is not the final consistency point.

1. Freeze all source deployment automation, including Doco-CD polling and webhooks and any other deployment controller on the source, and pause scheduled jobs, workers and queues per their service-specific rehearsed procedure. Record proof that no old writer can resume unexpectedly (for example: trigger disabled, token revoked or timer stopped, process stopped with the restart path also disabled). Site-specific commands come from the manifest, validated in rehearsal.
2. Quiesce application writers per store: the live inventory's write-path list determines the exact method per store (application-level fence, connection drain, service stop). Record the fence time and a verification probe showing writes are rejected or drained.
3. Take the final consistent backup, or complete the explicitly rehearsed replication catch-up, using each store's supported consistent method (never a filesystem copy of a running database). Record: backup identity, checksum, and the consistency timestamp. This timestamp is the consistency point.
4. Hold writes until validation completes (section 9.3).

Zero acknowledged write loss accounting: from the consistency point until all fences are confirmed, no write may be acknowledged anywhere. If any service still acknowledged a write after the consistency point (a fence leak), record it in the write-loss ledger (section 9.8) before proceeding: the guarantee then depends on the reconciliation procedure, and the operator must escalate to the owner before switching traffic.

### 9.3 Restore and validate the target, start dependencies in order

1. Restore target stores and files from the final backup using the rehearsed procedures, with the observed database majors preserved (never a major upgrade inside the cutover). Record restore identity and duration.
2. Verify each store's recorded integrity checks (counts, roles, extension/version metadata, seeded markers, checksums) and each client-facing contract from an external vantage: application auth, GraphQL/API, feature delivery, upload access, gateway policies.
3. Start dependent services in the recorded dependency order with external side effects still disabled (section 8.3 matrix still applies on the target until 9.5).
4. Validate identity: the target serves the approved release (digests, config hash) and reports readiness. A successful deployment request, container count, PID file or DNS lookup alone cannot satisfy the gate.

### 9.4 Switch routing and client connections

DNS and TTL plan (obtain real values in section 6; the mechanics):

- Lower public record TTLs to the owner-approved short value ahead of the window (planning default to confirm: 60 to 300 seconds), at least one full previous-TTL window before cutover, and record the exact times.
- At switch: update approved public records to the target. Keep source writes fenced throughout convergence.
- Convergence wait: old TTL plus a margin (planning default: previous TTL plus one interval), because resolvers and clients cache answers beyond your control.
- Long-lived connections: clients that already hold connections (HTTP keep-alive, WebSockets, database and SDK connections, gateway upstreams) do not re-resolve DNS. The manifest lists each client class and how it converges: restart or reconnect on the client side, connection drain on the source, or an accepted bounded overlap with source writes still fenced. Overlap is safe for reads only where the service is genuinely read-only on shared state; anything with shared writes waits for full drain.
- Verify from the external vantage: public names now answer with the target, application contracts pass, private admin names still fail from the public internet.

### 9.5 Enable target writers and record the first write

1. Enable target writers, queues and jobs only after section 9.3 and 9.4 checks pass.
2. Record the first write: exact timestamp (UTC), first service and store, operator identity, and the release/deployment identity active at that moment. From this instant the rollback class is post-write (section 9.7 B). The record lives in the cutover evidence.

### 9.6 The 24-hour acceptance soak (resumable, never a sleeping process)

The soak is a series of check batches, not one long command and not an agent waiting in a blocking sleep:

1. Cadence: the owner sets the batch interval (recommended starting point to confirm: every 5 to 15 minutes automated, with an hourly summary). Each batch runs the implemented smoke/health/backup/source-fence interfaces and the rehearsal-validated probe set, records pass/fail/blocked with a run ID and UTC timestamp, and compares against the manifest thresholds. Missing required interfaces prevent this stage from starting; manual preparation is not an execution fallback.
2. Coverage rule: the soak completes when at least 24 hours of successive batches have passed since the first-write timestamp, with no more than the owner-approved gap between batches (planning default: no batch gap over 30 minutes; a missed batch requires a decision, not silence).
3. Resumability: any interruption resumes from the last recorded batch timestamp; a batch failure triggers section 9.7.
4. Human review: the operator (and ideally the secondary) reviews batch summaries at agreed intervals rather than babysitting a terminal. Handoff at shift change includes the last batch ID.
5. Also verify during the soak: backups run and complete on schedule, private admin remains private, source stays fenced and stopped (no old writer resumed), and resource usage stays within the manifest headroom.

### 9.7 Rollback state machine and decision tables

Two classes exist, selected by exactly one fact: has the target accepted any acknowledged write (section 9.5 record)? Before the first write, class A applies. After it, class B applies, and no DNS-only action is permitted.

Class A: before any target write.

1. Stop or disable the target's public serving and any partially enabled components.
2. Return routing/connections to the unchanged source (DNS back to source values, clients reconnect per the manifest's connection plan).
3. Check source health (it was frozen, not broken): stores intact, services start, contracts pass.
4. Resume source writers (unfreeze in reverse order of the freeze), record unfreeze timestamp.
5. Post-mortem the defect, repair, and only then plan a new cutover attempt with a new final backup. No data loss occurred if the ledger (9.8) is empty.

Class B: after any target write. Stale-source DNS rollback is prohibited: the source data predates the acknowledged target writes, so pointing traffic back would silently discard them.

1. Immediately fence all writers on both sides (target writes stopped, source stays fenced), preserving target state. Record the fence timestamp.
2. Preserve the target state (no deletion, no overwrite, keep the backups).
3. Choose, with the owner per the escalation rule, between:
   - Forward repair: target remains authority; fix the defect forward following the rehearsed procedure; resume target writers after verification; source remains fenced for later retirement.
   - Copy-back: export target-side changes since the consistency point, replay them into a validated source restore, verify consistency with the recorded queries, then deliberately choose which side resumes authority (typically the source if the target defect is structural), then resume its writers. This is executable only if the copy-back prerequisites were rehearsed (section 9.7.1); otherwise forward repair is the default.
4. Resume a writer only after consistency verification; record everything in the evidence.

Decision table (thresholds are owner-set manifest values; the procedure, not improvisation, follows a breach):

| Trigger (breach class) | Writes happened? | Immediate action | Recovery path | Who decides |
|---|---|---|---|---|
| Private admin endpoint exposed from public internet | Either | Close exposure at the firewall/listener level; do not unfreeze writers | Fix, re-verify boundary suite; soak restarts only on owner approval | Operator; owner informed |
| Auth/API/flag failure rate above threshold | No | Freeze target writers (none active), class A | Class A steps 1 to 5 | Operator on duty |
| Auth/API/flag failure rate above threshold | Yes | Fence both sides immediately | Class B steps 1 to 4, forward repair default | Operator, owner for authority choice |
| Data-integrity discrepancy above zero tolerance | Yes | Fence both sides immediately | Class B copy-back if prerequisites met, else owner decides repair path | Owner |
| Sustained error/latency regression beyond threshold | Either | If No: class A; if Yes: fence both and class B | As left column | Operator on duty |
| Storage/resource exhaustion | Either | Do not delete data; fence writers first if writes are the pressure source | Grow within approved budget or class B; owner decides spend | Owner for spend |
| Remaining maintenance time below manifest minimum with cutover incomplete | No | Abort to class A (target not yet written) | Class A; reschedule with a new backup | Operator on duty |
| Remaining maintenance time below minimum after first write | Yes | Do not rush; stabilize, then class B forward repair decision with owner | Class B | Owner |
| Backup failure or missing consistency point before switch | No | Abort before switch; fix backup; class A not needed (nothing switched) | Re-run section 9.2 after repair | Operator |
| Any acknowledged write after the consistency point (fence leak) | Yes | Treat as a data-loss risk: escalate to owner before any switch | Reconcile via the rehearsed procedure or abort with owner | Owner |

### 9.7.1 Copy-back prerequisites (must exist before the window opens)

- Change capture on the target from the first-write moment: database WAL/binlog/audit export or application-level change ledger, per store, validated during rehearsal.
- A rehearsed reconciliation script and verification queries (which records prove the replay was complete and correct).
- A documented acceptance procedure: who verifies, what evidence closes the incident.
If any prerequisite is missing, class B copy-back is unavailable; forward repair or an owner decision are the only paths, and the manifest must say so in advance.

### 9.8 Write-loss ledger (zero acknowledged writes proof)

| Field | Content |
|---|---|
| Consistency point | Backup ID, checksum, UTC timestamp |
| Fence completion times | Per store and per controller, with the verification probe result |
| Acknowledged writes after the consistency point | Count and description (target: zero before section 9.5; source: must be zero after fences) |
| First write record | Timestamp, service, store, release identity |
| Final verdict | "Zero acknowledged write loss: yes/no", with any exception and its owner-accepted disposition |

The soak, smoke and restore evidence combine with this ledger to close G5.

### 9.9 Retention after cutover

Keep the source host stopped and fenced for at least 7 days after cutover, with independently recoverable backups. The owner may extend that window. Do not resume source writers or delete resources during retention; destructive retirement belongs to P6 and requires its own approval. A shorter period is outside this runbook and would require a reviewed change to the governing migration contract and issue acceptance, not merely a manifest entry.

## 10. Stage: retirement and operations handover (P6-01, issue #667, gate G6)

### 10.1 Sequence

1. Confirm the retention window is complete, the acceptance soak passed, and a post-cutover restore check has been performed: prove that a restore from the current production backup onto a fresh disposable target succeeds (same mechanics as the P3 cold restore; record duration and integrity results). This is the recovery proof that justifies removing redundant authority.
2. Record which old controllers, hosts, credentials, networks and tooling can be retired, and which must be retained (issue #667 lists Doco-CD deployment ownership removal, Portainer retirement if it has no recorded remaining purpose, legacy generator/drift automation narrowing). Local service Compose development and any explicitly retained legacy tooling stay.
3. Revoke obsolete tokens, age recipients and SSH permissions only after proving recovery access with replacements (issue #667: replacement access exercised, and a recovery path from independent protected storage demonstrated).
4. Update README, AGENTS.md, project skills and operational docs to the new source of truth and command paths; keep agent guidance short with links; preserve standalone Compose local development; mark older Swarm documentation as legacy scope.
5. Demonstrate the routine operations matrix (10.2) through the new interfaces, record maintenance schedules and alert ownership, and attach final evidence links to the epic.

### 10.2 Routine operations handover matrix (executable after this stage)

Each row routes to [delivery.md](delivery.md) for the detailed workflow. The "required interface" column names the interface the workflow depends on as specified in [work-items.json](../work-items.json); until that interface is implemented, the row is manual-only or blocked as marked, and the owning issue is the tracker. Never claim an interface exists because this table lists it.

| Routine task | Route | Required interface (status) | If not implemented |
|---|---|---|---|
| Add a service / create an environment | delivery.md | Service catalog and adapter flow from #660, registry check `platform-registry-check` | Manual catalog addition blocked until #660/#657 paths merge; do not hand-edit generated deployment units |
| Promote an image/config change | delivery.md | Promotion pipeline from #661 (`platform-promote-test`, CI action) | Promotions blocked; changes ride the manual path only with owner approval and full evidence |
| Inspect logs and health | delivery.md | Observability from #663 (`platform-observability-test`, `platform-smoke`) | Use the private dashboards (Grafana/Beszel via tailnet) and document gaps |
| Rotate secrets | delivery.md | SOPS flow from #659 (`platform-secrets-test`) | Rotation blocked until the delivery path is tested; never rotate by hand-editing target state |
| Restore data | delivery.md | Restore workflow from #662 (`platform-restore-test`) | Manual restore only with owner approval, using rehearsed commands |
| Recover Dokploy platform | delivery.md | Dokploy platform backup/restore from #662/#657 | Recovery requires the independently stored platform state and pinned installer |
| Recover tailnet/admin access | delivery.md | Tailnet recovery procedure (owner account, auth keys); account and credential recovery starts from [workstation.md](workstation.md) | Start from workstation.md account recovery; never rebuild access from the broken host alone |
| Replace a host | delivery.md | Re-provisioning flow (Pulumi program plus baseline, `platform-preview`, promote) | Blocked until the provisioning pipeline is implemented and rehearsed |
| Compatible rollback | delivery.md | Release/rollback mechanics from #661 with schema compatibility checks | Blocked; app rollback must respect DB schema compatibility regardless of tooling |

### 10.3 Destructive retirement of legacy resources (separate approval, exact identities)

1. Prepare a separate teardown plan: exact old-host/volume/snapshot/network IDs to destroy, retained backup references (IDs and where they live), cost impact (what stops billing and when), and the authorization reference for those exact resources. Do not hide data deletion inside lab cleanup or infrastructure refactoring.
2. Obtain or point to the explicit authorization for those exact resource IDs (recorded explicit approval naming those exact IDs: an explicit session authorization, repository environment protection, or an approved change record).
3. Execute: destroy only the listed IDs; verify each by its exact ID in the Hetzner console or `hcloud` CLI before and after.
4. Residual cost check: confirm in billing that only intentionally retained resources remain (Hetzner bills until deletion, so verify nothing chargeable lingers, including snapshots and backup objects); record the check with a date and the expected residual monthly cost.

### 10.4 Ownership credential and controller removal (only with proof)

Remove Doco-CD deployment ownership for migrated resources and retire Portainer only when no remaining purpose is recorded. Before removing any ownership credential or controller: the replacement access is proven to work (a routine operation has been executed through the new interface, and a recovery path from independent protected storage has been exercised). Record what was removed, when, by whom, and the proof reference.

## 11. Optional gateway evaluation boundary (P7-01, issue #668)

P7 is optional and excluded from core completion. It starts only after P6. It must not block, reopen or destabilize the completed migration: experiments use isolated synthetic traffic, the original APISIX release and etcd recovery artifacts stay intact, and any production gateway replacement requires its own bounded change and cutover plan with regression evidence. The core runbook's gates G0 through G6 close the migration without this stage.

## 12. Restoring independent access when the target (or your access) is lost

Recovery always starts outside the failed host:

1. Regain a workstation and accounts per [workstation.md](workstation.md): Git access, approved CI identity, Hetzner account, Pulumi backend, and independently stored recovery material (age keys, SSH bootstrap, tailnet admin, DNS admin).
2. Recover identities from independent protected storage (the canonical requirement). If the only copy of critical material is unreachable or unverified, escalate to the owner and stop the affected stage.
3. Re-provision from versioned state: run the infrastructure program from the repo with the approved backend, preview, and confirm the target comes back as new infrastructure (the Pulumi state remains the source of resource identity; the host's loss is a replacement event, not a state edit).
4. Apply the verified Ansible baseline and the pinned Dokploy lifecycle; restore Dokploy's own platform state (its PostgreSQL and `/etc/dokploy` mapping) from its independently stored backup if needed.
5. Restore application stores and files from the off-host backups using their documented consistency and version methods; verify integrity and contracts as in section 9.3.
6. Reconcile service registration in the target registry, promote the verified release, and re-verify private access and backups.
7. Execute this target recovery sequence only after the delivery/restore interfaces and procedures exist and have passed their required tests. Missing target tooling is a blocker, not permission to improvise equivalent mutations. If an incident affects the still-authoritative legacy source, follow its existing approved operational runbook instead of this unverified target plan.

Hard rule: a backup system that requires the lost Dokploy instance to reveal its only restore credential is unacceptable; verify during preparation that restore credentials live outside the host (and outside the Dokploy instance itself).

## 13. Evidence template

Store non-secret evidence under `.artifacts/platform/<run-id>/` with `manifest.json` plus named assertion reports and exact commands and exit codes (the canonical record per [validation.md](../validation.md)). Secret-bearing material goes only to the owner's restricted storage as opaque references. Fill one record per stage:

```markdown
## Evidence record: <stage name> (<issue #>, <gate>)
- Run ID and date (UTC): <run-id>, <date>
- Candidate: release <sha>, infra <sha>, repo checkout <url>@<sha>
- Environment and tier: <lab|rehearsal|production>, <tier>
- Operator(s) and approver: <names/roles>, approval references: <refs>
- Commands executed: <exact command list with exit codes>
- Tool/provider/image versions and digests: <versions>, <digests>, architecture <arch (native|emulated)>
- Assertions: <passed list>, <failed list>, <blocked list with reason>, <skipped list with approved applicability>
- Deployment identity/readiness: <release identity>, <readiness proof>
- Network boundary: <public/private probe results with vantage location>
- Data: <backup IDs, checksums, consistency point, restore duration, integrity results>
- Rollback/recovery exercise: <class exercised, outcome, evidence>
- Soak: <start first-write timestamp, batch count, interval, gaps, threshold observations>
- Cleanup/orphans: <destroyed IDs, orphan search result, retained items with owner and expiry>
- Residual risks/resources and cost: <list>, <budget usage against cap>
- Blockers and follow-ups: <exact missing input/interface with owning issue>
```

Allowed result states are pass, fail, blocked and skipped; a required blocked or skipped item prevents its gate from passing; never convert "not run" into pass.

## 14. Assignment-ready checklists per issue

Copy the relevant block into the issue or PR and tick with evidence links.

### #664 Rehearsal (P4-01, G3)

- [ ] G0 through G2 evidence verified for the candidate commit
- [ ] Dedicated isolated rehearsal project/credentials/names/DNS/state/budget under recorded explicit approval; production verified neither addressed nor imported
- [ ] Resource inventory with captured costs, ceiling formula and expiry approved; soak and contingency hours included
- [ ] T2 suite passed on the disposable VM (inputs complete; no missing-input pass)
- [ ] T3 orchestration executed from a clean checkout at the candidate commit: preview, apply, baseline, pinned Dokploy, private network, secrets, registration, promotion
- [ ] Synthetic state seeded; update/rollback, fresh-host restore, reboot, mount recovery, credential failure, admin denial and controller outage exercised
- [ ] Outside-tailnet and authorized probes run (IPv4/IPv6, direct ports, private Host/SNI)
- [ ] Full cutover rehearsal: fencing, final backup, traffic switch, pre-write rollback, post-write failure with stale-DNS rollback rejected
- [ ] 24-hour resumable soak completed with recorded batches and no blocking sleep
- [ ] Cleanup: only rehearsal-owned resources destroyed, exact-ID verification, zero-chargeable-orphan confirmation or retention with owner and expiry
- [ ] Decision record attached (versions/digests, measured downtime/RPO/RTO/headroom, blockers); site procedures handed to section 9 consumers

### #665 Production target and canary (P5-01, G4)

- [ ] Passing rehearsal evidence applies to the same candidate commit
- [ ] Separate production authorizations recorded (preview application, budget, canary isolation)
- [ ] Concrete production preview recorded with replacement/deletion analysis (none against live source)
- [ ] Fresh target provisioned; old host untouched and serving throughout
- [ ] Canary isolation matrix complete and verified with tests/logs; no shared live writes; no public DNS change
- [ ] Private access, test-name routing, architectures, headroom, backups, restart recovery verified; digests match the approved record
- [ ] Manifest complete with no unresolved required field; recorded explicit approval of its content (channel or content hash reference recorded)
- [ ] Pre-cutover drift recheck performed; affected gates rerun for material changes
- [ ] `make platform-evidence-validate ENV=production` passes; a blocked result is handoff evidence that prevents the gate, never acceptance

### #666 Cutover (P5-02, G5)

- [ ] Approved manifest identities used; freshness of backup and validation evidence verified; drift stop respected
- [ ] All source controllers frozen; every write path fenced; no-writer-resume proof recorded
- [ ] Final consistent backup with identity, checksum and consistency point; write-loss ledger opened
- [ ] Target stores restored with observed DB majors; integrity and client contracts verified from an external vantage
- [ ] Routing switched with the recorded TTL plan; source writes fenced through convergence; long-lived connection convergence per client class
- [ ] Target writers enabled only after checks; first-write record complete
- [ ] 24-hour acceptance soak passed with recorded batches; threshold breaches followed the decision table
- [ ] Zero acknowledged write loss verdict recorded (ledger closed)
- [ ] Source host stopped/fenced and independently backed up for the retention window; single owner per migrated workload
- [ ] `make platform-cutover`, `platform-smoke`, `platform-evidence-validate` all pass; a blocked or failed result is handoff evidence that prevents the gate

### #667 Retirement and handover (P6-01, G6)

- [ ] Retention window completed; post-cutover restore check proven
- [ ] Retire/retain list recorded for controllers, hosts, credentials, networks and tooling; local Compose development preserved
- [ ] Doco-CD ownership removed for migrated resources; Portainer disposition recorded; revocations only after replacement-access proof
- [ ] README/AGENTS/skills/docs updated; no misleading legacy quick start
- [ ] Routine operations matrix demonstrated (section 10.2); maintenance schedules and alert ownership recorded
- [ ] Destructive teardown separately approved for exact resource IDs; executed and verified by exact ID
- [ ] Residual cost check recorded (nothing chargeable lingering; expected residual monthly cost stated)
- [ ] Final evidence links attached to the epic; `platform-ownership-check` and `platform-ops-verify` both pass; a blocked or failed result is handoff evidence that prevents the gate

### #668 Optional gateway evaluation (P7-01, excluded from core)

- [ ] Live route/consumer/plugin inventory plus synthetic request corpus documented required behaviour
- [ ] APISIX standalone tested first; compatibility results recorded per behaviour; hot reload and rollback tested
- [ ] Kong evaluated only against a concrete unmet requirement, with honest DB-less/OIDC/GUI/decK comparison
- [ ] Gateway-simplification option assessed if only routing/TLS is proven
- [ ] ADR with measured results and an explicit retain/simplify/replace decision; production replacement would need its own cutover plan
- [ ] No impact on the completed migration; original APISIX release and etcd recovery artifacts retained

## 15. Stop and abort quick reference

Stop the affected mutation (and record evidence) when any of these is true:

- Target, source, project or credential identity is ambiguous or unverifiable.
- An actual image or data version contradicts the approved record or the plan.
- A required test failed, is blocked, or was skipped without an approved applicability rule.
- A secret appears in any output; contain it per [workstation.md](workstation.md) and rotate through the tested path before continuing.
- A delete or replacement falls outside the approved scope.
- Two controllers own the same service.
- A source or target writer cannot be fenced.
- Recovery evidence is invalid, or a backup requiring the lost instance to reveal its own restore credential is discovered.
- A manifest required field is unresolved, or an owner-set threshold, window or budget is missing.
- A required interface is unimplemented at the checkout. Manual preparation can produce a handoff packet, but cannot waive its execution guard.

Abort means: execute the applicable rollback class (section 9.7), preserve all evidence and state, notify the owner and secondary operator with the exact trigger, and wait for a new authorized window. Never improvise public access, force deletion or a stale-DNS rollback as a remedy.

## 16. Sources and change record

External behaviour relied on here, with primary references from [sources.md](../sources.md): Hetzner billing (hourly with monthly cap, billed until deletion, https://docs.hetzner.com/cloud/billing/faq), Hetzner cloud firewall private-network behaviour (S17), Docker published-port firewall behaviour (S18), Dokploy installation/deployment/backup contracts (S09, S10, S11, S12, S13, S14, S15), PostgreSQL 18 storage layout caution (S22), Tailscale GitHub integration scoping (S16). All AniTrend-specific decisions come from the repository contracts, not from these sources.

This runbook documents procedure only; it executes nothing and claims no runtime verification. Changes to gates, targets or ownership decisions must be made through the canonical documents and reviewed together with this file.
