# Start here: platform implementation and operations handoff

This is the handoff for [AniTrend platform migration #652](https://github.com/AniTrend/local-stack/issues/652). It assumes a new operator has no tools, accounts, credentials, running lab, or prior conversation context. Follow the linked chapters in order. You can assign a chapter to another person; its prerequisites and acceptance evidence travel with it.

The platform is not migrated by merging code. Development can ship on stacked pull requests while infrastructure is unavailable. A check that was not executed remains **blocked** or **skipped**, never **pass**. No document or local schema validator grants cloud spending, production access, traffic-switching authority, or data-deletion authority.

## 1. Choose your starting point

| Your task | Start with | Result |
|---|---|---|
| Start on a clean Ubuntu or Apple Silicon Mac workstation | [Workstation setup](workstation.md) | Git access, isolated pinned tools, explicit local Docker context, local lab and container verification |
| Reconcile what is actually running, finish infrastructure and VM acceptance | [Inventory and host](inventory-and-host.md) | Reviewed runtime inventory, provider/account inputs, trusted SSH, private access, storage safety, real VM acceptance |
| Implement and validate Dokploy, private ingress, secrets, deployments, CI, backups and monitoring | [Delivery and recovery](delivery.md) | Assignment-ready work for #657 through #663 and its actual-instance validation procedures |
| Rehearse, prepare production, cut over safely and retire the old owner | [Migration and handover](migration.md) | Explicit approvals, complete cutover inputs, writer fencing, recoverable data, soak and retention evidence |

Do not run a later chapter merely because a preceding issue is closed. Read its tested commit, environment, architecture and required results. A missing credential blocks only the stage that uses it; it does not prevent local development.

## 2. Systems and ownership, in plain language

| System | What it does here | What it must not do |
|---|---|---|
| GitHub | Stores reviewed source, pull requests and CI results | Store private keys, raw environment exports or customer backups |
| Docker local lab | Runs disposable test containers on your workstation | Stand in for real VM firewalls, disks, Tailscale or cloud-provider validation |
| Pulumi | Records and reconciles cloud VM, network, firewall and volume infrastructure | Deploy application containers to the target or keep the only production state copy on that target |
| Ansible | Configures the operating system, users, SSH, mounts, host firewall and Tailscale; later invokes pinned Dokploy bootstrap | Periodically redeploy Dokploy-owned applications |
| Dokploy | Owns target application deployments through a private management API | Co-manage the same workload with Doco-CD or deploy mutable unverified releases |
| Tailscale | Supplies narrowly granted private administrative connectivity | Make a dashboard private solely by giving it a private DNS name |
| SOPS and age | Encrypt configuration in Git and let authorized identities decrypt selected secrets | Make the failed target the only place recovery keys can be obtained |
| Legacy Doco-CD and Portainer | Continue their recorded ownership on the source host until explicit handoff | Automatically take over migrated applications after a failure |

The **source** is the current live host. The **target** is a fresh isolated replacement. Neither is the workstation Docker daemon. A **gate** is a set of acceptance conditions, not a shell command's exit status. A **release** binds a source commit, configuration hash, immutable image digests and target environment. A **fence** prevents a writer from restarting or accepting writes unexpectedly.

## 3. What is available in this delivery

This is an implementation-availability snapshot, not a copy of live GitHub issue status. Check the checked-out revision before following commands. The development chain is [#651](https://github.com/AniTrend/local-stack/pull/651), [#669](https://github.com/AniTrend/local-stack/pull/669), [#670](https://github.com/AniTrend/local-stack/pull/670), [#671](https://github.com/AniTrend/local-stack/pull/671). The workstation chapter explains how to fetch the required revision when these changes are not yet in `dev`.

| Work | Available code or remaining development | Acceptance still owed | Handoff chapter |
|---|---|---|---|
| [#653 / P0-01](https://github.com/AniTrend/local-stack/issues/653) | Read-only collector and schemas published in separate draft [PR #673](https://github.com/AniTrend/local-stack/pull/673); obtain its branch through the portable procedure before integration into this checkout | Actual disposable-daemon fixture acceptance, owner-confirmed host identity, every workload's disposition/owner, unmatched resources, external dependencies, DNS, data versions, recovery and complete environment inputs | Inventory and host, Part A |
| [#654 / P1-01](https://github.com/AniTrend/local-stack/issues/654) | Local Docker lifecycle, safety doctor, schemas, mocks and local container tests | Repeat on each declared native workstation/target architecture as applicable; retain exact evidence | Workstation |
| [#655 / P1-02](https://github.com/AniTrend/local-stack/issues/655) | Protected HCloud program and non-mutating preview wrapper | Account/backend recovery, real provider operations and an approved outbound policy before applying infrastructure | Inventory and host, Part D |
| [#656 / P1-03](https://github.com/AniTrend/local-stack/issues/656) | Inventory/trust adapter, OS/storage/Tailscale/firewall roles, container scenario and VM verifier | Actual VM storage preservation, host/private networking, Docker hooks, reboot/reconnect, zero-change second converge | Inventory and host, Part C |
| [#657 / P2-01](https://github.com/AniTrend/local-stack/issues/657) | Pinned Dokploy lifecycle and registry adapter still need implementation | Actual-instance create/update/deploy/failure/timeout/retry, identity/readiness, no duplicates, controller outage | Delivery, P2-01 |
| [#658 / P2-02](https://github.com/AniTrend/local-stack/issues/658) | Private ingress policy and multi-vantage probe suite still need implementation | Authorized access succeeds; public IPv4/IPv6, Host/SNI, direct-port and unauthorized tailnet/private-network probes fail | Delivery, P2-02 |
| [#659 / P2-03](https://github.com/AniTrend/local-stack/issues/659) | SOPS delivery, rotation and artifact scanning still need implementation | Intended-service canary, missing/failing/rotated values, success/failure/interruption cleanup, recovery copies | Delivery, P2-03 |
| [#660 / P2-04](https://github.com/AniTrend/local-stack/issues/660) | Catalog, deterministic service-source adaptation and immutable release records still need implementation | Preserved resource/network/health/storage semantics, service isolation and client/data behaviour | Delivery, P2-04 |
| [#661 / P3-01](https://github.com/AniTrend/local-stack/issues/661) | Private API promotion and CI policy integration still need implementation | Wrong identity/commit/digest, failed checks, untrusted/stale/replayed and concurrent jobs cannot deploy | Delivery, P3-01 |
| [#662 / P3-02](https://github.com/AniTrend/local-stack/issues/662) | Off-host consistent backups and cold-restore automation still need implementation | Fresh-target restore of data, users, roles, uploads and gateway/platform state; measured RPO/RTO | Delivery, P3-02 |
| [#663 / P3-03](https://github.com/AniTrend/local-stack/issues/663) | Service health, resource budgets and external monitoring tests still need implementation | User-visible checks plus deliberate failure detection outside the target failure domain | Delivery, P3-03 |
| [#664 / P4-01](https://github.com/AniTrend/local-stack/issues/664) | Guarded rehearsal orchestration and resumable soak evidence still need implementation | Approved actual Hetzner lifecycle, complete G2 checks, fresh restore, both rollback classes and 24-hour soak | Migration, section 7 |
| [#665 / P5-01](https://github.com/AniTrend/local-stack/issues/665) | Guarded production target/canary orchestration still needs implementation | Approved concrete preview, isolated canary without live writes or external side effects, complete cutover manifest | Migration, section 8 |
| [#666 / P5-02](https://github.com/AniTrend/local-stack/issues/666) | Cutover preflight, writer fencing and guarded execution still need implementation | Zero acknowledged write loss, safe pre/post-write recovery, first-write record, 24-hour acceptance | Migration, section 9 |
| [#667 / P6-01](https://github.com/AniTrend/local-stack/issues/667) | Ownership/operations verification and retirement orchestration still need implementation | At least 7-day retention, post-cutover restore, single-owner proof, routine operations and separately authorized retirement | Migration, section 10 |
| [#668 / P7-01](https://github.com/AniTrend/local-stack/issues/668) | Optional gateway experiment, not required for the core migration | Its own compatibility evidence and reviewed ADR before a separate change | Migration, section 14 |

The parent goal remains open until the core issues meet their acceptance criteria. These chapters are not a claim that unimplemented interfaces work.

## 4. Check command availability before assigning execution

On the workstation, from the selected repository revision:

```sh
make help
make -n platform-rehearse ENV=rehearsal
```

The second command only prints the recipe. If it prints `No rule for target`, that command is not implemented at your revision. Do not run it expecting a rehearsal. Assign its implementation first using the owning chapter and issue. Do not replace it with unreviewed direct cloud commands.

Read [the command contract](../validation.md#required-command-interface) for the complete required interface and [work-items.json](../work-items.json) for dependency links. Development on stacked prerequisites is authorized; operational acceptance and protected merges still obey their separate requirements.

## 5. Validate an existing local evidence record

The delivered `platform-evidence-validate` command is read-only. It recognizes the existing Docker lab and VM host-baseline evidence formats. It rejects missing checks, unfinished cleanup, nonpassing results, wrong environment/tier/commit, duplicate JSON keys and recognizable secret markers. It does **not** prove an artifact authentic, scan all possible secret formats, contact the host, or approve G0 through G6.

After completing the local lab including `platform-lab-down`, use the run ID printed by that lifecycle, and the full commit recorded for that run. From the repository root:

```sh
printf 'Completed lab run ID from the lab output: '
IFS= read -r LAB_RUN_ID
printf 'Full 40-character tested commit from the manifest: '
IFS= read -r TESTED_COMMIT
make platform-evidence-validate ENV=lab TIER=docker \
  MANIFEST=".artifacts/platform/lab/$LAB_RUN_ID/manifest.json" \
  COMMIT="$TESTED_COMMIT"
```

Expected: `evidence-validation=pass scope=docker-lab-lifecycle environment=lab tier=docker`. The command then prints its limits. Exit 2 means stop acceptance and read the non-secret reason. A manifest from a run cleaned up before its tests finished must fail even though cleanup succeeded.

After a successful real VM run, use the manifest path printed by `platform-host-verify` instead, with `TIER=vm`. Expected scope: `host-baseline`. A Docker report cannot substitute for it. No VM report can by itself prove Dokploy, application, network-boundary, restore, promotion or production acceptance. Record the separate tests required by the issue.

Do not edit evidence to turn failure into success. Correct the underlying issue and rerun the affected check. A report's source fingerprint and dirty-worktree flag remain material context; checking the recorded commit is not authentication of its bytes. Preserve the tested source revision and evidence together in the approved evidence store. Review content before sharing even when the recognizable-secret scan passes.

## 6. Required handoff packet

Before assigning a stage, give its next owner:

1. Work ID and full GitHub issue URL; exact source and prerequisite PR revisions.
2. This runbook chapter, the command's implementation status, and the next concrete action.
3. Named operator, reviewer and person authorized to approve spend, traffic or deletion for that stage.
4. Required accounts/permissions and **references** to recovery material, never credential values.
5. Environment/provider/project/host/volume identities, architecture/image versions and applicable dependency graph.
6. Passing, failing, blocked and skipped checks separately, with exact commands, exit statuses, run IDs and tested commits.
7. Restricted evidence location and retention, cleanup/residual resource inventory and any expiry/cost owner.
8. Approved abort thresholds and pre/post-write recovery procedure for mutating stages.

If one of these is missing, name the missing input and the person/system that supplies it. Continue independent development; do not guess an identity, enable public administration or substitute a successful HTTP response for runtime proof.

## 7. Completion rules

- Code delivered means reviewed implementation is available at a referenced commit or PR, with actual local verification listed.
- Runtime accepted means every required applicable assertion passed against the recorded actual system. Documentation, mocks, check mode and previews alone cannot establish this.
- A blocked/skipped required assertion prevents its gate from passing. A written blocked report is useful handoff, not acceptance.
- Rehearsal, canary, cutover and destructive retirement are separate stages. Approval for development does not approve them.
- Existing service-local configuration and legacy deployment instructions remain authoritative until each workload's recorded ownership handoff.
