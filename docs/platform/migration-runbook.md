# Migration recovery and cutover contract

This is the required runbook structure. P0 supplies runtime facts; P4 rehearses the completed instructions; P5 executes a concrete manifest. Do not run production commands from unresolved examples.

For step-by-step setup and assignment-ready procedures, start with the [operator runbooks](runbooks/README.md). In particular, [migration execution and handover](runbooks/migration.md) expands this safety contract with input-acquisition steps, approvals, expected evidence, abort decisions, rehearsal, soak, retirement and recovery instructions. Future command interfaces are labelled unimplemented rather than presented as executable deployments.

## Planning defaults and required inputs

Use a fresh target host and keep the source. Preserve database major versions. Default engineering targets are backup RPO no worse than 24 hours and cold-restore RTO no worse than 60 minutes for durable app state; these are targets to measure, not promises. The planned quiesced cutover must lose zero acknowledged writes. P0 must set and justify any different target.

Default rehearsal and post-cutover acceptance soaks are 24 hours. Retain the fenced old host and independently recoverable backups for at least 7 days after cutover. Resource spend, storage retention and the maintenance window must be confirmed before the relevant mutation. Do not invent an availability SLA from a single-host deployment.

The concrete cutover manifest requires: candidate release and infra commit, old/new project/server/volume/stack IDs, current/target image digests and DB majors, DNS records/TTL, private access/certificates, workers/cron/webhooks/queues, every write path, freeze/resume commands, backup/restore identities and checksums, recovery credentials references, maximum maintenance duration, abort thresholds, observed restore time and the selected pre/post-write recovery procedure. Required values cannot remain TBD at G4.

## Recovery dependencies

Recovery starts outside the failed host:

1. Access Git, approved CI identity, Hetzner account and durable Pulumi backend.
2. Recover scoped bootstrap/SSH/tailnet identities and SOPS age material from independent protected storage.
3. Provision the host/network/volumes and apply the verified baseline.
4. Install the tested Dokploy version and restore its platform state if needed.
5. Restore application stores and files using their documented consistency/version methods.
6. Reconcile service registration and promote the verified release.
7. Check data, application behaviour, private access, backups and external monitoring.

A backup system requiring the lost Dokploy instance to reveal its only restore credential is unacceptable. Provider VM snapshots, replicas and infrastructure state are not substitutes for tested application data backups.

## Persistent asset coverage

| Asset | Required investigation and restore proof |
|---|---|
| PostgreSQL, if active | Actual major/PGDATA, extensions/roles, consistent logical or supported physical backup, compatibility and row/content checks |
| Mongo | Actual topology/data layout, consistent backup method, users/indexes and data checks; avoid blindly reproducing ambiguous volume mounts |
| Redis | Determine cache versus durable state; AOF/RDB recovery or approved recreation with client-impact tests |
| APISIX etcd | Version-compatible snapshot/export recovery, routes/consumers/plugins and secret-safe validation |
| GrowthBook and flags | Mongo data plus uploads and configuration; client SDK/proxy/streaming and admin checks |
| Grafana/other UIs | Provisioning plus state and required users/settings; private exposure |
| Dokploy | Its PostgreSQL plus /etc/dokploy and registry mapping; platform recovery separate from app data |
| Telemetry/Beszel/other volumes | Retain or deliberately discard according to data classification, with cost/retention documented |
| Infrastructure/credentials | Pulumi backend, key/identity recovery, DNS configuration and independent access |

Use named volumes with explicit stable identities. Dokploy volume backups do not cover arbitrary bind mounts, and archiving a live database filesystem is not assumed consistent. Backup and restore implementations must use the database's supported method for its observed version/topology. Never restore into the original live volume as a test.

## Rehearsal

P4 uses synthetic data or an explicitly permitted sanitized/encrypted copy on isolated old/new fixtures. Run the actual hcloud program, baseline and deployment pipeline. Test fresh restore, host reboot, wrong credentials, backup failure, source writer fencing, traffic switch, pre-write rollback and failure after target writes. Measure recovery/maintenance durations and data integrity.

External probes must run outside the target's failure domain and tailnet. Verify real public IP/ports, private Host/SNI, IPv6, private-network filtering, authorized tailnet access and required client flag/API traffic.

## Production canary

P5-01 applies the authorized concrete preview to the fresh target. Keep existing public DNS and source writes unchanged. Use test hostnames and isolated data. Disable background workers, scheduled jobs and external side effects; a read-only UI does not imply the application is read-only. Prove the target cannot accidentally write to live stores or send real messages/webhooks.

Before cutover, re-collect targeted inventory and compare to rehearsal. Revalidate changed images, manifests, credentials, network rules, storage or schema. Do not repeat unrelated tests whose evidence remains valid.

## Cutover sequence

1. Verify approval scope, identities, release, available recovery time and fresh backup destination. Abort if the target/source cannot be identified unambiguously.
2. Freeze all source deployment automation including Doco-CD polling/webhooks. Quiesce writers, drain workers/queues and stop scheduled jobs according to their service-specific procedure.
3. Take a final consistent backup or complete an explicitly rehearsed replication catch-up. Record the source consistency point; hold writes until validation is complete.
4. Restore/validate target stores and files with the observed database majors. Start dependent services in the catalog's dependency order, with external side effects still disabled.
5. Verify integrity, readiness, admin isolation, client behaviour and release identity using target/test routing.
6. Switch public routing/DNS and client connections as recorded. Account for old DNS caches and existing connections: keep source writes fenced throughout convergence.
7. Enable target writers/jobs only after checks pass; record the first-write timestamp. This changes which rollback procedure is safe.
8. Observe agreed health/error/latency/resource thresholds, ensure backups run and complete the acceptance soak. Retain source resources fenced/stopped as planned.

A PID file, container count, successful deployment request or DNS lookup alone cannot satisfy the cutover gate.

## Rollback semantics

Before any target writes, rollback can stop the target, return routing/connections to the unchanged source, then resume source writers after source health is checked.

After target writes, returning to stale source data may lose acknowledged changes. Fence both sides, preserve the target state and use the rehearsed reconciliation/copy-back or forward-repair procedure. Only resume a writer after consistency verification. DNS-only rollback is prohibited at this stage. App image rollback is independent of DB schema rollback and requires backward compatibility.

Specify concrete thresholds in the cutover manifest: failed auth/API/flags, data-integrity discrepancy, private endpoint exposure, sustained error/latency regression, storage/resource exhaustion and remaining maintenance time. A threshold breach leads to the recorded procedure, not improvised public access or force deletion.

## Retirement and operations

After G5, retain the old host for the specified window. At G6, prove a post-cutover restore and revoke unused deployment authority. Update AGENTS, project skills and README to the new interface. Retain any legacy tooling still needed for local development or explicitly retained workloads.

Old-host/volume destruction is a separately identified irreversible operation. Prepare exact resource IDs, retained backup references and cost impact and use the authorization already in force or obtain the missing final approval. Do not hide data deletion inside lab cleanup or infrastructure refactoring.

The handover must make these tasks executable: add a service, create an environment, promote an image/config change, inspect logs/health, rotate secrets, restore data, recover Dokploy or tailnet access, replace a host and perform compatible rollback. Break-glass SSH remains available for incidents; it is not the routine deployment interface.
