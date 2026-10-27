# Delivery and recovery runbook: P2 Dokploy integration and P3 delivery

Status: execution runbook for work items P2-01 through P3-03 (issues [#657](https://github.com/AniTrend/local-stack/issues/657), [#658](https://github.com/AniTrend/local-stack/issues/658), [#659](https://github.com/AniTrend/local-stack/issues/659), [#660](https://github.com/AniTrend/local-stack/issues/660), [#661](https://github.com/AniTrend/local-stack/issues/661), [#662](https://github.com/AniTrend/local-stack/issues/662), [#663](https://github.com/AniTrend/local-stack/issues/663)). Written against repository state at commit `11535ba` on `feat/platform-ansible-656`, reviewed 2026-10-27. Parent epic: [#652](https://github.com/AniTrend/local-stack/issues/652).

None of the P2 or P3 components is implemented at the reference commit. This runbook describes what to build, who builds it, and how a later operator validates it on disposable VMs before any production gate. It never converts a missing runtime prerequisite into a passed gate.

## 0. How to read and use this runbook

Read first, in order: [workstation.md](workstation.md) (workstation and account setup), [inventory-and-host.md](inventory-and-host.md) (live inventory and host baseline inputs), [migration.md](migration.md) (recovery and cutover contract). Canonical contracts remain [ADR 0001](../adr-0001-platform-ownership.md), [validation.md](../validation.md), [current-state.md](../current-state.md), [agent-execution.md](../agent-execution.md) and [work-items.json](../work-items.json).

Three command classes appear in this document. They are not interchangeable.

| Label | Meaning | Where it may run |
|---|---|---|
| DEV | Authoring or research step for the implementer. Produces repository changes. No runtime effect. | Workstation, no deployment touched |
| GATE | Existence or prerequisite check. Confirms a command, file or credential exists before anything runs. Never mutates the target. | Workstation or target as labelled |
| OPS | Operator procedure against a real environment. Runnable only where labelled, only in the named environment tier, and only after the matching GATE passes. | Labelled per command |

Every OPS command block starts with a comment naming the operator location (workstation, disposable VM, CI runner) and mutation scope (`none`, `disposable-VM`, `lab`, `production-authorized-only`). Production mutation is never authorized by this runbook; production stages belong to the P4/P5 issues and their own manifests.

Hard rules carried through every section:

1. One deployment owner per resource. Dokploy owns migrated applications; Ansible owns the host and the Dokploy install lifecycle; Doco-CD stays on the legacy host only; Pulumi never deploys application containers.
2. Evidence states are pass, fail, blocked and skipped. A required blocked or skipped test prevents the gate ([validation.md](../validation.md)). Missing infrastructure is blocked, not pass.
3. Never print, commit or upload secret values, raw inspect or environment dumps, database contents or private keys. Keep raw exports in independent restricted storage outside the public checkout.
4. Never expose the Dokploy dashboard, gateway administration, Grafana, the Traefik dashboard or feature-management administration publicly, not even temporarily.
5. Do not change database major versions during this migration; preserve the observed major.
6. The legacy host keeps its existing recorded deployment owner and operational runbook until handoff. Freeze its controllers and writers only at the approved cutover step, not while preparing the new platform.

## 1. Purpose and glossary

Dokploy is the application operations layer: a self-hosted web UI and HTTP API that manages Docker Compose and Swarm-based deployments behind its own Traefik ingress. Per ADR 0001 it is event-driven deployment management, not assumed continuous drift reconciliation: a merged branch is not a deployment, and every deployment is an explicit promotion with recorded identity.

Terms used below:

- Registry: the versioned mapping from each stable AniTrend logical service ID to its resolved Dokploy project, environment, server, compose resource, app name, image digest and configuration hash per environment.
- Release record: the immutable identity of one deployment: source commit, rendered configuration hash, image digests and platforms, and the check results that authorized it.
- Adapter: the small deterministic program that turns authored service-local Compose/config sources plus target overrides into a release bundle, and calls the Dokploy API to register, update and deploy it.
- Fence: an actively enforced stop on writers or deploy automation so that a migration or rollback cannot race live changes.
- Canary: a deliberately injected marker (secret, record, file) used to prove exactly where data flowed and that cleanup happened.
- Fixture: a disposable deployment unit (not production data) used to exercise the full path.

## 2. Status and action matrix

Status at the reference commit `11535ba` is verified fact, not assumption. The branch implements P1: `make platform-doctor|lab-up|lab-test|lab-down|pulumi-test|preview|ansible-test|host-verify` exist, and the parent added `make platform-evidence-validate ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_40_HEX_SHA`, which validates existing `lab-run.v1` or `host-verify.v1` evidence records (identity, required assertions, zero-change counts, cleanup, recognizable secret markers). Its output is explicitly scoped to docker-lab-lifecycle or host-baseline evidence; it is never a G0-G6 gate approval and never validates later deployment schemas.

Every P2/P3 target below currently falls through to the Makefile `.DEFAULT` rule, which prints `No rule for target "<name>"; unimplemented platform commands fail closed.` and exits 2. Verified by dry-run for `platform-dokploy-test` at the reference commit. `deploy/dokploy/` does not exist. That is the correct fail-closed behaviour; do not fake a pass.

| Work ID | Issue | Status at 11535ba | Development needed (offline-authorable) | Later actual acceptance | Prerequisites | Required command interface (today: fails closed) |
|---|---|---|---|---|---|---|
| P2-01 | #657 | Not implemented | Dokploy bootstrap role, pinned installer capture, API adapter, registry, fixture deploy flow | T2 disposable VM; re-proven inside T3 rehearsal | P1-02, P1-03 | `make platform-dokploy-test ENV=lab`; `make platform-registry-check ENV=lab TIER=vm` |
| P2-02 | #658 | Not implemented | Public/private ingress split config, allowlist catalog, Tailscale grants, probe suite | T2 VM then T3 rehearsal probes | P1-02, P1-03, P2-01 | `make platform-network-test ENV=lab TIER=vm`; `make platform-network-test ENV=rehearsal` |
| P2-03 | #659 | Not implemented | SOPS-to-Dokploy delivery adapter, dotenv schema, cleanup contract, canary scan suite | T2 VM leak matrix | P1-01, P2-01, P2-02 | `make platform-secrets-test ENV=lab`; `make platform-artifact-scan ENV=lab` |
| P2-04 | #660 | Not implemented | Deterministic source-to-bundle adapter, unit catalog, volume identity map, fixture contracts | T2 VM redeploy/data tests; T3 rehearsal | P0-01, P1-01, P2-01, P2-02, P2-03 | `make platform-render ENV=lab`; `make platform-compose-test ENV=lab`; `make platform-release-verify ENV=lab` |
| P3-01 | #661 | Not implemented | Promotion workflow, release journal, concurrency and staleness controls, OIDC wiring | T2/T3 promotion and rollback exercise | P1-02, P2-01, P2-02, P2-03, P2-04 | `make platform-ci-contract-test ENV=lab`; `make platform-promote-test ENV=lab TIER=vm`; `make platform-release-verify ENV=lab` |
| P3-02 | #662 | Not implemented | Backup matrix, per-store backup/restore tooling, off-host destination, restore rehearsal scripts | T3 fresh-VM cold restore | P0-01, P2-01, P2-03, P2-04 | `make platform-backup-test ENV=lab`; `make platform-restore-test ENV=lab TIER=vm`; `make platform-artifact-scan ENV=lab` |
| P3-03 | #663 | Not implemented | Health/smoke contracts, network-aware telemetry config, alerts, budgets, failure drills | T2/T3 drills and external monitor proof | P0-01, P2-02, P2-04, P3-01 | `make platform-smoke ENV=lab TIER=vm`; `make platform-observability-test ENV=lab TIER=vm` |

Development columns are ordered by the prerequisites above; within P2, #657 precedes #658, which precedes #659, which precedes #660. #661 and #662 can be developed in parallel after P2-04; #663 needs #661.

## 3. Ownership and authoring boundaries

| Path | Owner | Rule for this runbook |
|---|---|---|
| `deploy/dokploy/` | New platform code (created by P2-01/P2-04) | Adapter, registry, pin capture, catalog live here. Authored source. |
| `tools/platform/` | New platform code | Scripts behind new Make targets, following the existing `lab.py`/`ansible_runner.py` pattern. |
| `ansible/roles/` + `ansible/` playbooks | Ansible host baseline | A Dokploy bootstrap/upgrade role extends the P1-03 baseline; it invokes the supported pinned installer lifecycle only. |
| `infra/pulumi/hcloud/` | Pulumi | VM/network/volume/firewall/DNS provisioning. Never deploys containers. |
| Service folders (`traefik/`, `apisix/`, `mongo/`, `redis/`, `postgres/`, `growthbook/`, `observability/`, `edge-graphql/`, `on-the-edge/`, `website/`, ...) | Service-local authored source | Read as inputs to the adapter. Adapter may add target-specific override files next to sources; do not edit a service to emulate the target. |
| `stacks/` | Generated output | Never edited by hand; legacy drift checks must keep passing until the retirement phase changes their scope. |
| Legacy `deploy/doco/`, `doco-cd/` | Legacy host only | No new work; do not point at the new host. |
| `.artifacts/platform/<run-id>/` | Evidence output | Ignored, non-secret only. Secret-bearing evidence goes to independent restricted storage. |

## 4. Where a novice obtains each account, token and setting

Nothing in this table is stored in Git. Each row names where the thing is created, what role is needed, who authorizes it, and the check or stop condition.

| Item | Where a novice obtains it | Access needed | Who authorizes | Check / stop condition |
|---|---|---|---|---|
| Hetzner project, API token | Hetzner Cloud Console, project Security page, API tokens | Project owner grants only the scope required for the stage; read-only for inspection, write only for an approved apply | Platform owner | Verify the intended project ID in the console, then perform a read-only list using the approved credential-loading path. Never paste a token into a command saved in shell history. Stop if the project or token scope differs from the approved record |
| Hetzner VNC console | Hetzner Console, server detail page, Console icon | Project owner | Platform owner | Used only to verify SSH host keys per [inventory-and-host.md](inventory-and-host.md); stop if the console cannot be reached |
| Pulumi Cloud account and token | app.pulumi.com signup/invite; personal access token under profile settings | Organization member for the pinned org | Platform owner | `pulumi whoami --verbose` shows the expected backend and identity ([pulumi-hcloud.md](../pulumi-hcloud.md)); stop on any other backend |
| Tailscale admin access | login.tailscale.com with the company identity provider | Owner, Network admin or Admin role (required to create OAuth clients and ACLs) | Platform owner | Admin console opens the correct tailnet; stop if you land on a different tailnet |
| Tailscale tags and ACL grants | Admin console, Access controls (ACL file) and Tags pages | Network admin | Platform owner | `tailscale status` on the target shows the approved tag; unauthorized device test in section 8 must fail |
| Tailscale auth key / OAuth client / federated identity | Admin console, Settings, Keys or OAuth clients; federated identity per Tailscale GitHub Action docs (client ID plus audience) | Network admin | Platform owner | Key is tag-scoped, ephemeral where applicable, reusable only for CI; stop if the key has no tag or broad scope |
| Tailscale HTTPS certificates | Admin console, DNS page: enable MagicDNS and HTTPS Certificates; then `tailscale cert <machine>.<tailnet>.ts.net` on the host | Host root plus tailnet membership | Platform owner | Machine name contains nothing sensitive before enabling (names publish to the Certificate Transparency ledger); stop if a sensitive name is enrolled |
| DNS provider for public zone (if not HCloud) | Provider dashboard (for example Cloudflare), zone page | Zone admin | Platform owner | Zone matches the P0-01 inventory record; the Pulumi program only manages DNS when `dns_provider_ref` is `hcloud`, so any other provider is manually or externally owned |
| Cloudflare (or equivalent) DNS-01 API token | Provider dashboard, API tokens page, scoped to Zone.DNS Edit for the exact zone | Zone admin | Platform owner | Token passes a read of the zone and fails on other zones; store as a secret reference only |
| GitHub repository admin | Repository Settings, Environments, Secrets, Branch rules | Repo admin (environments on private repos require a GitHub Team or Pro plan; verify the plan before designing around them) | Platform owner | Protection rules saved and visible; stop if plan limits block required rules and record it as an external blocker |
| Dokploy admin account | Created once at first visit to the freshly installed dashboard on port 3000, from the tailnet path only (section 6) | Designated operator | Platform owner | Credentials live in the approved password manager; stop and isolate if the setup page was reachable from the public internet before the account existed |
| Dokploy API token | Dashboard, profile settings, API/API keys page, after admin login | Designated operator | Platform owner | Token stored as a GitHub environment secret or lab-only variable; verify a harmless GET (for example `project.all`) works; stop if the token grants more than the documented role allows |
| SOPS age identity | `age-keygen -o keys.txt` on a trusted workstation; public key appended to `.sops.yaml` key_groups | Platform owner | Platform owner | Public key in `.sops.yaml`, private key escrowed in independent restricted storage (section 9); a lost private key with the current single-recipient config means unrecoverable files: escrow before any new encryption |
| Backup destination and credentials | Owner-selected S3-compatible store (bucket plus scoped key) | Platform owner | Platform owner | Recovery credentials must be independently available without the failed Dokploy host. Target-side backup credentials may have a protected copy there, but it must not be the only recoverable copy. Test list/put/get/delete only on the dedicated rehearsal prefix |
| External monitoring account | Owner-selected external uptime/alerting service | Platform owner | Platform owner | Probe target recorded in the P0 inventory; alert destination tested with a deliberate failure (section 11.7) |
| Maintenance window, RPO/RTO, budget ceiling | Decision by platform owner, recorded in the P0 inventory | n/a | Platform owner | Missing values block the applicable gate; do not proceed with invented numbers |

### 4.1 Install the extra tools for your assigned stage

The workstation chapter supplies Git, Docker, Python, Node/npm, Pulumi and Ansible. It does not assume GitHub CLI, SOPS, age, the Tailscale workstation client or database backup clients already exist.

| Tool | First-time installation and location | Read-only check before continuing |
|---|---|---|
| GitHub CLI (`gh`) | Follow the OS-specific [official installation instructions](https://github.com/cli/cli#installation) on the workstation. Use `gh auth login` and `gh auth setup-git` for authenticated work; never put a token in a URL | `gh --version`; `gh auth status` identifies the intended account without printing its token |
| SOPS (`sops`) | The P2-03 implementer selects an exact [official release](https://github.com/getsops/sops/releases), verifies its published checksums/signatures by the release instructions, records the version and digest in the delivery tool lock, then installs the matching workstation/CI binary | `sops --version` must equal that reviewed lock. No lock yet means finish the development prerequisite before decrypting live values |
| age and `age-keygen` | Install for the workstation OS using the [official age instructions](https://github.com/FiloSottile/age#installation); record the selected version with the P2-03 tool lock. Generate private material only after choosing protected independent recovery storage | `age --version` and `age-keygen --help` succeed; neither command generates or prints a private key |
| Tailscale workstation client | Install from the [official OS-specific setup](https://tailscale.com/download), sign into the intended tailnet, then have its administrator grant only the required target access. This is separate from the target's Ansible-installed daemon | `tailscale status` identifies the expected device/tailnet; prove both an authorized and unauthorized path before relying on grants |
| HTTPS/API inspection tools | Install `curl` and `openssl` using the workstation OS package manager if absent. These inspect transport and certificates; they are not a secret store | `curl --version`; `openssl version`; use credential files/approved secret loading rather than token literals |
| Database backup/restore clients | P3-02 pins tools compatible with each observed server major/topology. Prefer the documented versioned database image/tool distribution; do not install a workstation's newest database server to obtain a client | Record the actual client version beside the source server version and image digest. An unknown major or missing client blocks that store's restore |

System/package-manager installation may require workstation administrator access. It is not authorization to change packages on the legacy host. Record installation versions in evidence, keep credentials out of downloaded archives and shell history, and do not replace a missing tool with plaintext secret handling.

## 5. Cross-cutting: Dokploy purpose, install pin, checksum and API schema capture

Applies to P2-01 and every later upgrade.

### 5.1 Pin policy (DEV)

Pin one exact Dokploy release per environment change and record it in `deploy/dokploy/pin.md` (created by P2-01) with:

- Dokploy version (for example the then-current stable; `v0.30.10` was the latest release when this runbook was written).
- The `install.sh` SHA-256 captured from that release's assets.
- The component versions the pinned installer itself installs, read from the installer source: at `v0.30.10` these were Docker `28.5.0` (held with `apt-mark hold` on apt systems), Traefik `v3.6.25` for `dokploy-traefik`, and `postgres:16` for Dokploy's own `dokploy-postgres` service.
- The verification date and the person/machine that captured the digest.

Dokploy publishes no upstream checksum for `install.sh`; the release contains the script as its single asset. The control is therefore: capture the digest at pin time, re-download later and require an identical digest, and treat any mismatch as a stop condition. Never pipe a remote script straight into a shell; download, verify the recorded digest, then execute.

The documentation explicitly warns not to install a specific version by exporting `DOKPLOY_VERSION` against the main `dokploy.com/install.sh` script; that script targets the latest release. For a pinned install, use the release asset of that exact version:

```sh
# LOC=workstation MUT=none  [GATE]
gh release download --repo Dokploy/dokploy v0.30.10 -p install.sh -O /tmp/install.sh
sha256sum /tmp/install.sh   # must equal the digest recorded in deploy/dokploy/pin.md
```

Digest captured while writing this runbook: `75f321e7e5b9dce38b1bf22b54b0f84afcdae510daf6f6f05539f631f94fd071` (`install.sh`, release `v0.30.10`, downloaded 2026-10-27). Re-verify at execution time; a different digest is a stop condition, not something to override locally.

### 5.2 Installer behaviour to expect (OPS, disposable VM)

The installer requires root, free ports 80, 443 and 3000, installs Docker if missing, runs `docker swarm init --advertise-addr <addr>` (preferring a private RFC1918 address on a real interface; `ADVERTISE_ADDR` overrides it, and must be passed inline when using `sudo` because sudo resets the environment), creates the attachable overlay `dokploy-network`, creates `/etc/dokploy`, stores `dokploy_postgres_password` and `dokploy_auth_secret` as Docker secrets, creates the `dokploy-postgres` service, the `dokploy` service (published `3000` with `mode=host`, `stop-first`, `parallelism 1`), and a plain `docker run` container `dokploy-traefik` publishing 80/443 TCP and 443 UDP. `/etc/dokploy` is created mode 777 by the installer; treat that directory as secret-bearing platform state and tighten its permissions as part of the host baseline rather than assuming the installer's default is intended.

If the HCloud private subnet plan overlaps Docker's default address pools, pass `DOCKER_SWARM_INIT_ARGS="--default-addr-pool 172.20.0.0/16 --default-addr-pool-mask-length 24"` (adjust to the P0 CIDR plan) in the same inline-sudo style.

Upgrade path for the pinned lifecycle: download the same release asset for the target version, verify its digest against the new pin entry, then run `sh /tmp/install.sh update` on the host. Record before/after versions in evidence.

### 5.3 API schema capture (DEV then GATE per upgrade)

The adapter must discover the API shape of the pinned instance, not assume the latest documentation matches it. Procedure:

1. Capture the documented reference for the pinned tag from docs.dokploy.com (domains: compose, deployment, project, environment, server, backup) into `deploy/dokploy/api-schema/` as versioned fixtures.
2. Probe the pinned instance read-only to confirm the shapes: with a valid token, `GET /api/project.all`, `GET /api/compose.search`, and one harmless detail read. Record observed request/response shapes (sanitized) next to the documented fixtures.
3. The adapter tests assert against these captured fixtures. Any upgrade re-runs this capture and updates fixtures in the same PR as the pin bump.

Endpoint facts to design against (from the documented API for the reviewed generation; re-verify against the pin): authentication is an `x-api-key` header; compose resources are created with `POST /api/compose.create` (requires `name` and `environmentId`; `appName` must match `^[a-zA-Z0-9._-]+$` and is at most 63 characters; `composeType` is `docker-compose` or `stack`; `sourceType` is `git|github|gitlab|bitbucket|gitea|raw`); environment content is set with `POST /api/compose.saveEnvironment` (`composeId`, `env`); deployment is triggered with `POST /api/compose.deploy` (`composeId`, optional `title`, `description`, `freshVolumes`) and `POST /api/compose.redeploy`; deletion is `POST /api/compose.delete` with an explicit `deleteVolumes` boolean; deployment history for compose units is `GET /api/deployment.allByCompose?composeId=...`; logs of a deployment are `GET /api/deployment.readLogs?deploymentId=...`; `POST /api/compose.cancelDeployment` cancels queued deployments (the UI notes in-progress deployments cannot be canceled); `composeStatus` values include `idle`, `running`, `done` and `error`. Treat these as the fixture baseline and record any pin-specific deviation.

## 6. Cross-cutting: initial private admin, account and token workflow

Goal for P2-01: a reachable, administrable Dokploy instance whose dashboard was never publicly reachable at any point. Sequence:

1. (Prereq) The disposable or rehearsal VM exists through the P1-02/P1-03 flow and is enrolled in the tailnet with the approved server tag ([inventory-and-host.md](inventory-and-host.md)). The HCloud firewall intent allows public inbound TCP 80 and 443 only, with SSH from explicit sources; port 3000 is not in the public allowlist. Cloud rules alone do not cover private-network traffic or Docker publication.
2. Before invoking the installer, the P2-01 bootstrap implementation must install the tested private dashboard listener/host/Docker policy: approved tailnet sources can reach setup, while public IPv4/IPv6 and unauthorized private-network sources cannot. Record how port 3000 is allowed privately through the actual Docker hook; the P1 lab inventory's empty application-route policy does not supply that allowance automatically. If that configuration is not implemented, stop here. From the verified private SSH path, run the checksum-verified installer as root on the disposable VM. Do not open a public firewall hole for port 3000.
3. Wait for observed service readiness, not a fixed elapsed-time assumption. Immediately verify the negative public IPv4/IPv6 and unauthorized private-network probes after the service publishes its port, then open first-run setup through the authorized tailnet path. The first visitor creates the admin account, so isolate setup before starting the service and complete it promptly. A public or unauthorized response is a failure, not a temporary exception.
4. Record the admin credentials in the approved password manager. Create the least-privileged API token(s) in profile settings and store them as references (GitHub environment secret for CI, lab-only environment variable for local runs). Verify one harmless authenticated GET.
5. Implement and test the dashboard's private HTTPS router before enabling its domain. Private DNS alone does not stop correct Host/SNI requests through a shared public listener. After the full private-route probe matrix passes, optionally remove the direct IP:port publish with the documented command `docker service update --publish-rm "published=3000,target=3000,mode=host" dokploy`. Keep verified private access working before and after; never expose the public route to recover a broken private one.
6. Record in evidence: install version and digest, first-boot time, admin account created (no credential values), token created (name and scope only), the probe result proving port 3000 is unreachable from a public vantage point.

Negative acceptance: from an external non-tailnet host, `curl -m 5 http://<public-ip>:3000` must fail (timeout or connection refused); the dashboard Host/SNI probe from section 8 must not return application content.

## 7. Cross-cutting: registry reconciliation identity and ambiguous-ownership recovery

Applies to P2-01 and used by every later issue. Design rules (ADR: idempotent reconciliation, fail on ambiguous ownership):

- The registry file `deploy/dokploy/registry/<environment>.json` maps each logical service ID to: Dokploy project ID, environment ID, server ID, compose resource ID, deterministic app name (`anitrend-<logical-id>-<environment>`), image digest, configuration hash, source commit and the deployment owner string. It is authored, versioned and schema-validated.
- Reconciliation is search-then-decide, never create-first: list existing resources filtered by the deterministic app name (for example `GET /api/compose.search?appName=...`); zero matches means create; exactly one match whose recorded environment and project match means update; anything else is ambiguous.
- Ambiguous states that must stop all mutation: two or more resources with the same deterministic app name; one match whose environment differs from the registry entry; a resource whose recorded owner is not `dokploy`; a registry entry referencing a resource that no longer exists.
- Recovery procedure for ambiguity (OPS, location: workstation over tailnet API; MUT: none until a human decides):
  1. Snapshot the candidate resources read-only (compose.one, deployment.allByCompose) into restricted evidence storage; record IDs, names, environments and last deployment status.
  2. The platform owner decides which resource is authoritative. Moves between environments use the API's move operation only as a deliberate operator action; CI never moves resources.
  3. Delete the losing duplicate with `POST /api/compose.delete` and `deleteVolumes: false` unless the owner explicitly decides otherwise; deleting with volumes is a data-destructive action requiring the same care as any deletion.
  4. Correct the registry file in a reviewed change, re-run the registry check, and append a journal entry (date, IDs, decision, who).
- `platform-registry-check` must verify the one-service-to-one-environment/one-server/one-owner invariant on every run and must fail (not repair) on ambiguity. Idempotence acceptance: two consecutive runs produce no new resources and no redeployments (the second run's only change is nothing).

## 8. Cross-cutting: network boundary probe plan

Applies to P2-02 and re-run inside P3/P4 acceptance. Grounding facts: Hetzner Cloud Firewalls are stateful and apply only to packets leaving the layer 2 domain, and they do not filter traffic inside a private network ("Can Firewalls secure traffic to my private Hetzner Cloud Networks? Not yet"). Docker publishes ports by writing NAT rules that divert traffic before ufw's INPUT/OUTPUT chains see it, so ufw status proves nothing about published containers; filtering happens via the host firewall's `DOCKER-USER` hook rules (the P1-03 role applies source and original-destination-port allow rules to DNATed forwarding on every ingress interface and drops other DNATed traffic). Private DNS names or tailnet membership alone are not boundaries.

Probe matrix (every row is an assertion in `platform-network-test`):

| ID | Source (operator location) | Target and method | Expected | Why |
|---|---|---|---|---|
| N1 | External non-tailnet host (any cloud box or home connection) | `https://<public-ip>/` with `Host: <private-admin-host>` on 443 | No admin application content: default/404 response or TLS cert mismatch, never a dashboard | Public allowlist must exclude private routes even with a correct Host header |
| N2 | External non-tailnet host | TLS SNI `<private-admin-host>` against public 443 | No admin content; certificate for that SNI must not be served publicly | SNI-based routing must not leak the private route |
| N3 | External non-tailnet host | Direct `curl -m 5 http://<public-ip>:3000` and `https://<public-ip>:3000` | Timeout or refusal | Dashboard port must not be publicly reachable |
| N4 | External non-tailnet host, IPv6 | Same as N1-N3 over the AAAA address when IPv6 is enabled | Same as N1-N3 | IPv6 must satisfy the same allowlist |
| N5 | External non-tailnet host | Direct published ports of databases/metrics/OTLP if any are published | Refused everywhere (public v4, v6) | No public database, metrics or OTLP ports |
| N6 | Authorized operator node on the tailnet | Private hostnames for Dokploy, Grafana, gateway admin, Traefik dashboard, feature admin | All reachable over HTTPS | Positive control; proves the private path exists |
| N7 | Second device on the same tailnet without an ACL grant (throwaway device or separate test user) | Same private hostnames | Denied by ACL policy | Tailnet policy, not just network reachability |
| N8 | Unrelated node in the same HCloud private network (a second disposable VM attached to the network) | Direct private IP:port for admin services and databases | Refused | Hetzner does not filter private traffic; only host rules can enforce this |
| N9 | Authorized tailnet node | CI path: ephemeral runner identity reaches exactly the deployment API endpoint and nothing else | Reachable endpoint, denied other ports/hosts | Scoped CI grants |
| N10 | After reboot and after a Dokploy redeploy | Repeat N1-N8 | Identical results | Boundaries must survive restarts and redeploys |

Required client traffic before privatizing feature-delivery endpoints: enumerate GrowthBook SDK, proxy, streaming and webhook traffic and Unleash SDK/webhook traffic from their official client documentation and the P0 inventory; administrative APIs stay private while required client endpoints remain on the public allowlist.

Private TLS: two viable documented paths; the decision and its inputs are recorded in the registry/ADR notes. (a) ACME DNS-01 through Traefik (the legacy source already declares a `tailscale` resolver using a Cloudflare DNS challenge, so the Cloudflare token is a known credential reference). Traefik renews ACME certificates itself; the operator duty is monitoring expiry (P3-03 alert) and verifying the resolver after redeploys. (b) Tailscale-provided certificates: enabling HTTPS in the admin console and `tailscale cert <machine>.<tailnet>.ts.net` issues Let's Encrypt certificates with 90-day validity; when delivered as files (as with `tailscale cert`) renewal is the operator's responsibility, which needs a scheduled renewal job and an expiry alert; names publish to the public CT ledger, so machine names must be clean before enabling. Test either path by first issuing against the Let's Encrypt staging resolver, then production; verify expiry dates (`openssl x509 -noout -enddate`) and that the P3-03 expiry alert fires on a deliberately short-dated test certificate.

Rollback rule from the issue: restore a known-good private access path before replacing firewall rules; never open all admin ports to recover convenience.

## 9. Cross-cutting: SOPS+age lifecycle

Applies to P2-03. Current repository facts: `.sops.yaml` matches `\.env(\.enc)?$` with a single key group containing exactly one age recipient; [docs/Managing Secrets.md](../../Managing%20Secrets.md) documents the encrypt/decrypt/cleanup workflow (`stackctl secrets` or direct `sops --encrypt --input-type dotenv --output-type dotenv .env > .env.enc`), cleanup with `shred -u` falling back to `rm -f`, and the legacy runner mounting the age key read-only at `/root/.config/sops/age/keys.txt` from host path `/opt/local-stack/sops/age/keys.txt`. SOPS resolves decryption identities from `SOPS_AGE_KEY_FILE`, `SOPS_AGE_KEY`, `SOPS_AGE_KEY_CMD`, or the default `$XDG_CONFIG_HOME/sops/age/keys.txt` (falling back to `~/.config/sops/age/keys.txt`). Verify the pinned `stackctl` build actually provides the documented `secrets` subcommands before documenting them as available; the locally installed `stackctl 0.4.0` help text examined while writing this runbook listed no `secrets` command, so treat the subcommand's availability as a GATE, and use direct `sops` commands as the fallback that always exists.

Least-privilege layout:

- One age identity per role and environment class: operator recovery key, CI delivery key, lab key. Lab and rehearsal use dummy values, never production values.
- The repository keeps only encrypted `.env.enc` files and `.env.example` placeholders. Decrypted plaintext exists only inside the delivery process's private temporary storage or memory.
- Key escrow: the private keys live in independent restricted storage (the owner's secret manager or an encrypted archive outside every host involved). With the current single-recipient `.sops.yaml`, the single private key is a total-loss single point; adding a second recipient per key group is a reviewed change that should accompany P2-03.
- Delivery into Dokploy goes through the tested API (for example `compose.saveEnvironment`) after explicit dotenv parsing that treats variable names and types as a schema: reject missing required variables, empty required values, duplicate keys, unsafe interpolation, and unhandled literal dollar signs, quotes and newlines. Do not rely on the Dokploy UI environment editor alone: documented behaviour is that UI variables are written to a `.env` file and are not automatically injected into containers; the compose file must consume them via `env_file` or `${VAR}` interpolation, which the adapter controls.
- Rotation: to rotate a compromised age key, first remove it from `.sops.yaml`, then for each encrypted file run `sops updatekeys <file>` followed by `sops rotate --in-place <file>`, commit and push, and only then rotate the actual credential values inside the files (SOPS documents that reversing the order can leave the compromised key able to recover data). Ordinary periodic rotation is `sops rotate --in-place <file>` per file plus a re-delivery to affected units. Rotation evidence records file paths, key IDs (public keys only) and exit codes, never values.
- Revoked/wrong-key behaviour must be tested: decryption with a revoked key fails closed and no deployment starts; a wrong-environment registry reference fails before any API call.

Canary leak matrix (all cases are assertions in `platform-secrets-test` and `platform-artifact-scan`):

| Case | Setup | Expected |
|---|---|---|
| Success | Canary value delivered to the intended fixture container only | Container env contains the canary; logs, Git status/diff, Pulumi outputs and state, uploaded artifacts, and all temporary files contain no canary |
| Missing required value | Remove a required variable from the encrypted source | Deployment refused before any API mutation; no partial state |
| Wrong environment | Present lab values to a rehearsal-named unit | Refused; nothing deployed |
| Partial API update failure | Interrupt between saveEnvironment and deploy | No deployment triggered from an unapproved partial state; next run reconciles cleanly |
| API outage mid-delivery | Stop the Dokploy service during delivery | Cleanup still runs (process exit, signal and timeout paths all covered); no plaintext leftovers; retry is safe |
| Interruption/timeout | SIGINT and hard timeout during decryption/cleanup | Same cleanup guarantees; the runner must not leave a plaintext temp file on any termination path |
| Backup leak check | Take a Dokploy platform backup and a restore-archive rehearsal | Archive is encrypted at rest in the off-host destination; scanning decrypted contents happens only inside the rehearsal, and the report contains no values |

Do not claim `shred` provides secure deletion on SSD or copy-on-write storage; the contract is "no plaintext left at rest in accessible locations", verified by scanning, not by wipe guarantees.

## 10. Cross-cutting: release identity and supply-chain linkage

Applies to P2-04 and P3-01. Every deployment unit's release record contains: source commit (full SHA), rendered configuration hash, image reference with immutable digest and platform, and the check results that authorized it. Images are consumed by digest from their owning pipelines (GHCR for AniTrend services). The catalog records per-unit source paths, runtime names, ownership, network dependencies, secret references, volumes, ingress exposure and health contract. Determinism acceptance: the same source commit and non-secret environment input produce the same normalized bundle hash and catalog.

Supply-chain notes grounded in the current sources: the etcd image is `bitnamilegacy/etcd:3.6.4` (a legacy-repository tag), so its digest and continued availability must be recorded during P0 and pinned by digest in the release bundle; Grafana provisioning is a bind mount (`./config/provisioning/`), and bind mounts are not covered by Dokploy volume backups, so the adapter must move such config into adapter-managed file mounts or config images for anything that must be backed up or survive re-clone (the Dokploy documentation states re-deployment re-clones the repository and clears its directory, breaking repo-relative file mounts).

## 11. Issue runbooks

Each issue section states: status, deliverables and owning paths, inputs, development procedure, command gates, VM acceptance procedure, acceptance criteria, negative cases, artifacts, failure recovery, and a signoff checklist. Acceptance wording condenses the linked issue; the issue remains the live contract.

### 11.1 P2-01, issue #657: bootstrap Dokploy and reconcile its service registry

**Status:** development needed; no VM acceptance yet.

**Deliverables and owning paths:** `ansible/roles/` Dokploy bootstrap/upgrade role invoking the pinned installer lifecycle; `deploy/dokploy/` with pin capture (section 5.1), API adapter (section 5.3), registry (section 7) and registry schema; `tools/platform/` scripts; root Makefile targets `platform-dokploy-test` and `platform-registry-check` following the existing fail-closed pattern.

**Inputs and credentials:** disposable Ubuntu 24.04 VM from the P1-02/P1-03 flow with signed host trust; Tailscale enrollment with the approved tag; Dokploy admin account and API token (section 6); the pin record with installer digest.

**Development procedure (DEV, workstation):**
1. Capture pin and API schema fixtures (sections 5.1 and 5.3).
2. Implement the adapter: create/update/deploy/status/logs operations as pure functions over the captured API, with an injectable HTTP client so offline tests use fixtures only (mocks cover adapter logic only, per the issue).
3. Implement registry reconcile with the section 7 state machine.
4. Implement the bootstrap role: idempotent, invokes the pinned installer only when the installed version differs, records `/etc/dokploy` and service state, never reinitializes Swarm on a working host.
5. Add the Make targets; every unimplemented prerequisite must exit non-zero with a specific explanation.

**Command gates (GATE, workstation):** `make -n platform-dokploy-test ENV=lab` and `make -n platform-registry-check ENV=lab TIER=vm` must not print the "No rule" fail-closed message; running each target without a VM must produce blocked evidence, not a pass.

**VM acceptance procedure (OPS, disposable VM; MUT disposable-VM):**
1. Baseline the VM through the P1-03 flow; enroll Tailscale.
2. Run the bootstrap role; verify the pinned version is installed (`docker service ls` shows `dokploy` and `dokploy-postgres`; `docker ps` shows `dokploy-traefik`).
3. Complete the private admin workflow (section 6).
4. Register one fixture compose unit (small image pinned by digest, trivial healthcheck) through the adapter; capture the returned deployment ID.
5. Poll `deployment.allByCompose` until terminal status; independently verify readiness with an HTTP request from the tailnet path; record the fixture image digest and confirm the running container matches it.
6. Run `make platform-registry-check ENV=lab TIER=vm` twice; the second run must create nothing and redeploy nothing.
7. Controller outage test: `docker service scale dokploy=0` on the disposable VM, confirm the fixture application keeps serving during the outage, then restore the service (`docker service scale dokploy=1`) and confirm the restored controller can redeploy the fixture. Record timestamps and the serving gap (expected: none for the application).
8. Verify git/image auto-deploy triggers are disabled for the CI-owned fixture unit.

**Acceptance criteria (from the issue):** repeatable bootstrap and reconciliation without duplicates or unintended redeploys; create/update/deploy/failure/timeout/retry paths tested against a disposable actual Dokploy VM; registry maps each logical service to exactly one environment, server and deployment owner; a simulated controller outage leaves the fixture serving and a restored controller manages it; private access wired without ever publishing the dashboard publicly.

**Negative cases:** duplicate registry creation refused on second run; ambiguous match (two resources with one app name) stops with a specific error; wrong-environment registry entry refuses; deploy endpoint returning HTTP 200 while the deployment ends in `error` is recorded as failure; missing token produces blocked evidence; ports 80/443/3000 occupied makes the installer fail cleanly with its documented error.

**Artifacts:** `.artifacts/platform/<run-id>/manifest.json` plus assertion reports; registry file diff; pin record; sanitized API fixture diffs; outage timeline. Secret-bearing raw state goes to restricted storage by reference only.

**Failure recovery:** installer failure on ports: stop the conflicting service or pick a different disposable VM; half-installed state: destroy the disposable VM and re-run from the role (no state worth preserving); failed registry state: section 7 recovery; stuck deployment: `POST /api/compose.cancelDeployment` for queued, `deployment.killProcess` for a wedged process, then redeploy.

**Signoff checklist:** PR merged with tested commit; both command targets run with recorded exit codes; environment/tier recorded; Dokploy, Docker, Traefik, Postgres versions and image digests plus architecture recorded; every acceptance checkbox above marked with evidence links; outage exercise attached; registry idempotence proof attached; no secret values in any artifact; owner signoff recorded.

### 11.2 P2-02, issue #658: isolate administration behind Tailscale and test ingress boundaries

**Status:** development needed.

**Deliverables and owning paths:** adapter configuration for separate public and private ingress (Dokploy keeps owning Traefik); service-to-network attachment catalog (edge, application, data networks; only ingress-needing services attach to the ingress network); explicit private binding/restriction with verification of the pinned release's actual Docker/Swarm publish semantics; Tailscale operator and CI grants documented as ACL changes; probe suite behind `platform-network-test`; DNS and TLS renewal decision record (section 8).

**Inputs:** the P0-01 public allowlist; tailnet name, tags and ACL policy (section 4); chosen private TLS path and its credential (Cloudflare DNS-01 token or Tailscale HTTPS); IPv6 enabled or explicitly disabled; the unrelated private-network probe node.

**Development procedure (DEV, workstation):**
1. Encode the allowlist: public routes as explicit inventory-derived entries; everything else private by default.
2. Model network attachments and aliases (documented aliases replace old Swarm stack-prefixed DNS names such as `infrastructure_traefik`).
3. Implement the probe suite so each row of the section 8 matrix is an individual assertion with its own pass/fail/blocked state.
4. Prove publish semantics empirically on the pinned release: publish a test port bound to `127.0.0.1` and to all interfaces and observe which is reachable from where; document the observed behaviour rather than assuming a bind address is enforced.

**Command gates:** `make -n platform-network-test ENV=lab TIER=vm` and `make -n platform-network-test ENV=rehearsal` must be implemented; missing probes or blocked rows prevent the gate.

**VM acceptance procedure (OPS, disposable VM plus one external probe host and one same-network probe node; MUT disposable-VM for config, none for probes):** run the full section 8 matrix; then reboot the VM and repeat; then trigger a Dokploy redeploy of the fixture and repeat the admin-isolation rows. Record each row's result with command, timestamp and vantage point.

**Acceptance criteria (from the issue):** private services unreachable from an external non-tailnet probe even with correct hostname/SNI, including direct IP/port and IPv6 when enabled; authorized operators and scoped CI connect while unauthorized tailnet identities cannot; public application and required client traffic still work and certificates renew without public admin listeners; host firewall enforcement proven with published containers rather than inferred from ufw status; Hetzner private traffic explicitly tested; reboot and redeploy preserve all assertions.

**Negative cases:** any N1-N5 row returning application content is an immediate fail and a stop condition for later phases; unauthorized tailnet device reaching a private service fails; a certificate renewal test that requires a public admin listener fails by design.

**Artifacts:** probe report per matrix row; ACL diff; TLS renewal record with certificate dates; publish-semantics observation note.

**Failure recovery:** if a private path is broken by a change, restore the previous known-good ACL/Traefik configuration from version control before touching firewall rules; never recover by exposing admin ports publicly; if DNS-01 renewal fails, fall back to the staging resolver to diagnose without burning production rate limits (Let's Encrypt rate-limit window applies).

**Signoff:** all applicable matrix rows pass, with reboot/redeploy repetitions, reviewed ACL diff and renewal proof attached. Any required blocked or skipped row remains a handoff item and prevents signoff.

### 11.3 P2-03, issue #659: deliver SOPS secrets to Dokploy without leaking deployment artifacts

**Status:** development needed.

**Deliverables and owning paths:** delivery adapter in `deploy/dokploy/` (dotenv schema parser, per-service/environment selection, API injection, cleanup); `tools/platform/` scan tooling for `platform-artifact-scan`; role/environment separation in `.sops.yaml` (reviewed change); documented precedence and file-secret rules; canary test fixtures under `tests/platform/`.

**Inputs:** existing `.env.enc` per service; age identities per role (section 9); dummy lab values; the Dokploy API token; decision on second-recipient redundancy.

**Development procedure (DEV):** implement the section 9 delivery contract (parse, validate, inject via the captured API, cleanup on every termination path, shell tracing suppressed, no secret-bearing uploads); implement the canary scanner over: process logs, `git status`/`git diff`, Pulumi outputs and state files, uploaded artifacts, temporary directories, and the fixture container's environment; implement rotation helpers that follow the documented updatekeys-then-rotate order.

**Command gates:** `make -n platform-secrets-test ENV=lab` and `make -n platform-artifact-scan ENV=lab` implemented; both must produce blocked (not passed) evidence when the VM/API tier is unavailable.

**VM acceptance procedure (OPS, disposable VM; MUT disposable-VM):** run the full section 9 canary matrix against a real pinned instance: success, missing value, wrong environment, partial update, API outage, interruption and timeout paths; verify with the scanner after each path; exercise one rotation and one revocation end-to-end and re-deliver to the affected fixture only.

**Acceptance criteria (from the issue):** a canary secret reaches only the intended fixture container; missing or wrong-environment values prevent deployment; canary scanning finds no secret in logs, Git changes, Pulumi inventory/state outputs, public artifacts or leftover temporary plaintext after every tested termination path; rotation/revocation and reapplication are repeatable and rollback restores references/versions without printing values; Dokploy's persistent secret-bearing surfaces (its database, container environment, deployment files) and backup encryption/access requirements are documented truthfully.

**Negative cases:** every leak-scanner hit is a stop condition and must be triaged before any further work; an unapproved partial state that triggers a deployment is a fail; a cleanup path that leaves plaintext is a fail even if the deployment succeeded.

**Artifacts:** scanner reports per case; rotation journal entry; updated secret-surface documentation; escrow confirmation (location reference only).

**Failure recovery:** restore the previous secret version/reference and redeploy only dependent services; never recover by committing decrypted files or disabling log redaction; if the age key is lost with no escrow, the encrypted sources are unrecoverable: restore the key from escrow, or re-create secrets from their upstream sources with owner authorization, and record the incident.

**Signoff:** all matrix cases with scanner-clean results, rotation/revocation evidence, documentation of Dokploy secret-bearing surfaces with backup encryption requirements, escrow location recorded, signoff recorded.

### 11.4 P2-04, issue #660: adapt service sources into reproducible Dokploy deployment units

**Status:** development needed.

**Deliverables and owning paths:** deterministic adapter in `tools/platform/` + `deploy/dokploy/` producing a versioned release bundle and a deployment-unit catalog; target override files next to service sources; named-volume identity map; fixture contracts for edge-graphql, on-the-edge, website, GrowthBook, the gateway trio, the stores and observability per the actual P0 inventory; Make targets `platform-render`, `platform-compose-test`, `platform-release-verify`.

**Inputs:** P0-01 live inventory (dispositions, actual image digests and architecture); the service-local sources; section 10 linkage rules; the discrepancy list below.

**Source facts to respect (verified in the service sources at the reference commit):**
- `postgres/docker-compose.yaml` pins the volume comment to a PG17 pre-18 layout while the image line says `postgres:18`: resolve the actual running major and PGDATA in P0 before any restore; never upgrade or downgrade the major as part of the move.
- `mongo/docker-compose.yaml` mounts one named volume at both `/data/db` and `/data/configdb`: record the actual layout; do not blindly reproduce ambiguous mounts.
- `redis/docker-compose.yaml` runs `--appendonly yes` with no explicit data volume mount: determine whether an anonymous volume or different live configuration holds durable state before classifying it as disposable.
- `apisix/api-gateway/config/apisix.yaml` is mounted as `conf/config.yaml` runtime configuration in traditional/etcd mode, not a standalone route export.
- `edge-graphql` has no container healthcheck (only a Traefik loadbalancer health path label); `on-the-edge` has its healthcheck commented out; `website` has none.
- `observability/prometheus/config/prometheus.yml` uses Swarm-era cross-stack DNS names (`infrastructure_traefik:8080`, `infrastructure_apisix_gateway:9091`) that must be rewritten to the new networks.

**Development procedure (DEV):** build the renderer with namespace-safe variable handling (pre-render per service or namespace shared `HOST`/`PORT` names; reject unresolved placeholders; verify interpolation separately from secret injection); preserve effective resource limits, restart policy, healthchecks, aliases and logging explicitly and report unsupported Swarm-only fields; group units by lifecycle and data dependency rather than reproducing the three legacy stacks; give every persistent asset a stable named volume identity that does not vary with project or release names; keep secret payloads out of the non-secret bundle; add the catalog with one mapped owner per active service and an explicit disposition for absent or retired ones (Portainer retained, PostgreSQL and Unleash not activated, APISIX+etcd preserved, no Kong).

**Command gates:** `make -n platform-render ENV=lab`, `make -n platform-compose-test ENV=lab`, `make -n platform-release-verify ENV=lab` implemented; legacy generated-stack checks (`stackctl sync` path in CI) must keep passing.

**VM acceptance procedure (OPS, disposable VM; MUT disposable-VM):**
1. Render and register the fixtures; verify `docker compose config` semantics (variable collisions, escaped literals, mounts, healthchecks, resource constraints, missing required dependencies each produce the designed outcome).
2. Deploy the fixture set; record bundle hash and release identity.
3. Redeploy after a fresh checkout/re-clone: seeded persistent data and provisioning files must survive; volume identities unchanged; verify with recorded volume names and content checksums.
4. Run `platform-release-verify` and confirm the deployed image digests match the release record exactly.

**Acceptance criteria (from the issue):** same source commit and non-secret environment produce the same normalized bundle hash and catalog with no hand-maintained duplicate manifests; compose config plus runtime tests cover the listed dimensions; redeploy after fresh checkout retains seeded data and provisioning with stable volume identities; every active service has one mapped deployment owner and every absent/retired service an explicit disposition; legacy generated-stack checks keep passing.

**Negative cases:** unresolved placeholder in any unit fails the render; duplicate variable collision fails; a volume identity that changes between deploys fails; an image tag (non-digest) reference in a release bundle fails; hand-edited generated output fails the determinism check.

**Artifacts:** bundle hash, catalog JSON, release records, volume identity map, redeploy data-survival checksums.

**Failure recovery:** reapply the previous verified release bundle and digests without deleting volumes; keep legacy sources until cutover evidence permits retirement; if a unit cannot be expressed in Compose mode, record the evidence and write the Stack-mode ADR before deploying it (no silent semantic loss).

**Signoff:** determinism proof (two renders identical), runtime test matrix, redeploy survival proof, catalog completeness versus the P0 inventory, signoff recorded.

### 11.5 P3-01, issue #661: promote verified releases through the private Dokploy API

**Status:** development needed.

**Deliverables and owning paths:** promotion workflow under `.github/workflows/` plus `tools/ci/` or `tools/platform/` helpers; deployment journal (append-only record of requested and effective releases per environment); release-record schema (section 10); rollback procedure with the data-compatibility gate; Make targets `platform-ci-contract-test`, `platform-promote-test`, `platform-release-verify`.

**Inputs and credentials:** GitHub environment `dokploy-promotion` (name per implementer) with protection rules (required reviewers up to 6, wait timer, deployment branch policy restricted to the integration branch, prevent self-review, administrators-bypass disabled as policy allows); environment secrets `TS_OAUTH_CLIENT_ID` and `TS_AUDIENCE` (Tailscale federated identity) or an OAuth client pair; the scoped Dokploy API token; the pinned API fixtures.

**Development procedure (DEV, workstation):**
1. Keep builds in their owning repositories; local-stack consumes GHCR digests.
2. Workflow shape: unprivileged PR validation stays separated; the promotion job references the protected environment; it requires `id-token: write` only for the Tailscale federated identity exchange; no PR/fork job receives production secrets or tailnet access; PR-head code is never executed under `pull_request_target` (the existing Renovate gate's base-checkout pattern is the in-repo precedent).
3. Promotion job: connect via the Tailscale GitHub Action (`tailscale/github-action@v4`, tags such as `tag:ci`, `ping` the deployment endpoint), pin the immutable release source, call the compose deploy API, then verify the result against the requested release by reading back deployment status and the running image digest; a deploy endpoint HTTP 200 is request acceptance only and never success.
4. Concurrency: one in-flight promotion per environment (workflow concurrency group keyed by environment); serialize Pulumi state updates separately; stale jobs (superseded runs) must detect that a newer release is already effective and abort without overwriting.
5. Journal: every promotion attempt writes requested release, outcome, effective release and actor to the journal file in the repository (sanitized) or the evidence store; the journal identifies the effective deployed release.
6. Rollback: explicit rollback to the previous image and configuration only when data/schema compatibility allows; an incompatible data migration blocks automatic rollback and defers to [migration.md](migration.md) procedures.

**Command gates:** the three targets implemented; `platform-promote-test` requires the VM tier and must report blocked without it.

**VM acceptance procedure (OPS, disposable VM plus CI runner; MUT disposable-VM):** deploy an approved fixture release by digest/commit and verify; then prove each negative: a failed prerequisite check, an untrusted artifact, a mismatched digest, a wrong-environment target, missing credentials, a timeout and malformed model output each prevent promotion; then run two promotions concurrently and verify serialization (the journal shows one effective release, no interleaved overwrites); then exercise rollback to the previous compatible release and confirm health; then attempt rollback across an intentional data-incompatibility marker and confirm the automatic rollback refuses.

**Acceptance criteria (from the issue):** approved fixture release deployed by digest/commit and verified; failed prerequisite, untrusted artifact or stale job cannot promote; two concurrent promotions cannot race the same environment or Pulumi stack and the journal identifies the effective release; rollback restores the previous compatible application release and health while incompatible data migrations block automatic rollback; existing Renovate safe-checkout/risk controls remain effective and every new mutation path is classified; branch protection and environment settings are read and documented from actual configuration, with unavailable admin permissions recorded as an explicit external blocker rather than assumed success.

**Negative cases:** listed above; additionally: a workflow marking success on HTTP 200 alone is a design fail (assert the verification step exists); duplicate webhook/image-watch triggers re-enabled for a CI-owned unit is a fail.

**Artifacts:** promotion run logs (sanitized), journal diff, environment settings screenshot or API export (no secret values), rollback exercise record, concurrency test record.

**Failure recovery:** disable the promotion entry point (workflow disabled) and retain the journal; restore the prior tested release only when the compatibility gate permits; never re-enable Doco-CD on migrated resources; if the Tailscale identity fails to connect, the job fails closed with a specific error and retries after the ACL or identity issue is fixed.

**Signoff:** all fixture negatives demonstrated, journal inspected by the owner, environment protection exported and attached, rollback and no-rollback cases both evidenced, signoff recorded.

### 11.6 P3-02, issue #662: implement off-host backups and prove cold restoration

**Status:** development needed.

**Deliverables and owning paths:** backup matrix document (or generated catalog) covering every persistent asset in the verified inventory; per-store backup/restore tooling under `tools/platform/` and `deploy/dokploy/`; off-host destination configuration (references only in Git); restore rehearsal scripts; Make targets `platform-backup-test`, `platform-restore-test`, plus reuse of `platform-artifact-scan`.

**Inputs:** backup destination and scoped credentials (independent of the host); the P0 inventory's per-asset facts (majors, topology, layout); the recovery dependency order and RPO/RTO targets from [migration.md](migration.md) (defaults: RPO no worse than 24 hours, cold-restore RTO no worse than 60 minutes for durable app state; measure and report actuals).

**Version-aware method baseline (verify each store's actual version/topology from the inventory before relying on any of these):**
- PostgreSQL (only if actually active): consistent logical dump with `pg_dump`/`pg_restore` or a supported physical method using the same major as the server; include users/roles and extension metadata; row/content checks after restore.
- Mongo: `mongodump`/`mongorestore` matched to the observed topology; resolve the one-volume-two-mounts layout first; verify users, indexes and content.
- Redis: classify durable versus cache with the owner; if durable, AOF/RDB recovery with the container stopped or a checked `SAVE`/`lastsave` point; if cache, an explicitly approved recreation with client-impact tests.
- APISIX etcd: `etcdctl snapshot save`/`snapshot restore` compatible with the observed etcd version; verify routes, consumers and plugins after restore; note the legacy image tag from section 10.
- GrowthBook: Mongo data plus the uploads named volume plus configuration; verify flag behaviour and admin access after restore.
- Grafana: provisioning (currently a bind mount, so the adapter must have moved it to a backed-up form per section 10) plus the `grafana-data` volume state; verify datasources, dashboards and users.
- Dokploy platform itself: the documented Web Server, Backups flow (requires an S3 destination; produces a zip of the `dokploy-postgres` database plus `/etc/dokploy`); restore clears `/etc/dokploy` and drops the database, then follow the documented post-restore steps (update server IP, reconfigure IP-based Git providers, update DNS, possibly restart Traefik and re-login).
- Pulumi state and credentials: Pulumi Cloud checkpoint history first; export to restricted storage only as a secondary copy; age keys, Tailscale bootstrap and restore credentials accessible from outside the failed host (migration.md: a backup system requiring the lost Dokploy instance to reveal its only restore credential is unacceptable).

**Development procedure (DEV):** implement the matrix with owner, consistency method, frequency, retention, encryption, destination, credential reference, expected size, restore order and recovery check per asset; implement failure detection and alerts (missing/expired backups alert; failed restore drill alert); seed synthetic data with countable markers for restore verification; keep production data out of local tests and public artifacts.

**Command gates:** the three targets implemented; `platform-restore-test` requires the VM tier.

**VM acceptance procedure (OPS, two disposable VMs: source and fresh restore target; MUT disposable-VM):**
1. Seed markers into every store; run the backup suite; record backup identity, timestamp, checksums.
2. Simulate failure; restore onto the fresh VM using only code, secret recovery and backup artifacts (no reads from the original host).
3. Start services in catalog dependency order; verify marker counts and content, roles, uploads, gateway rules, flags, app authentication and private access (section 8 rows N6 only).
4. Measure recovery time (RTO) and the restore point age (RPO); compare to targets; a miss is a finding with owner acceptance or a target revision, not a silent pass.
5. Run the restore with separately scoped restore credentials to prove the credential split.

**Acceptance criteria (from the issue):** every durable asset has a tested restore path or an explicitly approved discard/rebuild classification; a fresh-host restore succeeds without reading the original host; measured RPO/RTO meet targets or revised targets have explicit owner acceptance; failed/missing/expired backups are detected and alert; restore uses separately scoped credentials; evidence reports backup identity/time/checksums without exposing customer data or secrets.

**Negative cases:** raw tar of a running database volume is rejected as a consistent backup; a restore that touches the original live volume is prohibited (never restore into the original live volume as a test); a backup job that silently skips an asset fails the matrix check; an unencrypted backup in the off-host destination fails the scan.

**Artifacts:** backup matrix, per-asset restore transcripts with checksums, RPO/RTO measurements, alert-firing evidence, credential-scope proof.

**Failure recovery:** backup creation must not mutate production data; restore only into an explicitly identified empty disposable target until cutover authorization; failed restore: fix the method against the actual version/topology and repeat; credential loss: recover from escrow per section 9/10 before any restore attempt.

**Signoff:** matrix complete and reviewed, one full cold restore evidenced, RPO/RTO recorded, alert test attached, signoff recorded.

### 11.7 P3-03, issue #663: verify service health, resource budgets and deployment observability

**Status:** development needed.

**Deliverables and owning paths:** health and smoke contract per enabled unit in the catalog; rewritten telemetry configuration (scrape targets, Grafana datasources and provisioning) for Dokploy's networks; alert rules covering public endpoint failure, deployment failure, data volume space, OOM/restart loops, certificate expiry and backup age or failed restore drills; budget measurement record; operator UI runbook and break-glass path; Make targets `platform-smoke` and `platform-observability-test`.

**Inputs:** actual upstream application endpoints verified from each owning repository or image (no invented `/health` routes, no requirement for `curl` inside images that lack it); measured baseline resource usage; the external monitoring destination.

**Development procedure (DEV):** define readiness/liveness per unit (Dokploy deployment status alone is not readiness); update `observability/prometheus/config/prometheus.yml` scrape targets and Grafana provisioning for the new network aliases (current cross-stack names are Swarm-era); prove one request's trace/log/metric correlation where supported; investigate the APISIX global-rule declaration against actual runtime configuration; set memory/CPU/log/disk/retention limits from measured values including Dokploy overhead and build avoidance on the production host; record deployment IDs, release digests and environment in observability without secrets.

**Command gates:** the two targets implemented with the VM tier.

**VM acceptance procedure (OPS, disposable VM plus external monitor; MUT disposable-VM):**
1. Positive: healthy smoke requests succeed for every unit; telemetry survives a redeploy with valid runtime names; dashboards reachable only privately (section 8).
2. Deliberate failures, each followed by restoration: fail a readiness check (gate refuses), stop an application (alert fires), stop the Dokploy controller (external monitor detects what internal tooling cannot), remove a backup schedule (backup-age alert), interrupt telemetry ingestion (detection documented), fill a test volume toward its limit (space alert).
3. External detection: with the host or controller unavailable, the external monitor still detects and notifies the recorded destination; attach the notification proof.
4. Record measured load, latency and resource use; verify the full target fits within the chosen VM size without unverified memory assumptions.

**Acceptance criteria (from the issue):** healthy smoke requests succeed and intentionally unhealthy services fail the gate (a running process or container count alone is insufficient); telemetry survives redeploy with valid runtime names and dashboards are private; alert tests demonstrate external detection when the host or controller is unavailable with a documented notification destination; measured load/latency/resources and chosen limits are recorded; routine inspect, logs, compatible rollback and redeploy are possible through the documented workflow without an interactive host shell.

**Negative cases:** a unit passing with no health contract is a fail; an alert that cannot fire in the drill is a fail; an internal-only detection claim during a controller outage is a fail.

**Artifacts:** health contract per unit, drill transcripts with timestamps, budget record, alert destination proof, break-glass path document.

**Failure recovery:** restore previous tested configuration, provisioning and limits; never make metrics or admin endpoints public to debug ingestion; controller outage recovery follows section 11.1 step 7 in reverse (restore the service, verify management).

**Signoff:** all drills evidenced, external detection proven, budgets recorded, break-glass path documented, signoff recorded.

## 12. Evidence, signoff and handoff

Follow [agent-execution.md](../agent-execution.md) evidence requirements. Per-issue sanitized evidence lists: implemented paths, PR and tested commit; exact commands with exit results; environment and tier; actual versions, digests and architecture; assertions with pass/fail/blocked/skipped and reasons; deployment identity/readiness, network boundary and data-restore proof where relevant; rollback exercise and current ownership; residual risks and follow-up links.

Non-secret evidence lives in `.artifacts/platform/<run-id>/` (manifest plus named assertion reports and exact commands/exit codes). Raw exports, keys, database contents and backup payloads go to independent restricted storage and are referenced opaquely. The parent-provided `make platform-evidence-validate ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_40_HEX_SHA` validates lab-run and host-verify records and their redaction markers; later deployment-era schemas will need their own validators (nonpassing or unknown schemas exit 2 by design). Evidence is never a gate approval; gates are claimed only when every applicable assertion is pass.

Each issue closes only when its acceptance criteria are satisfied and merged under repository policy, with the signoff checklist of its section completed by the platform owner.

## 13. Missing site facts that block later acceptance

These inputs are development-blockers for the labelled acceptance tier, not for offline authoring. Do not invent them.

| Missing fact | Blocks | Obtain from | Who authorizes | Check / stop condition |
|---|---|---|---|---|
| Verified public allowlist and dispositions | #658, #660 acceptance | P0-01 live inventory | Platform owner | Inventory complete; stop if a service has no disposition |
| Tailnet name, tags, ACL policy, CI identity type | #658, #661 | Tailscale admin console | Platform owner | Grants tested by N7/N9; stop on broad unscoped grants |
| Private TLS path decision and credential | #658 acceptance, renewal tests | Section 8 decision inputs | Platform owner | Renewal verified in staging first; stop on production-CA trial failures before diagnosing |
| Backup destination, credentials, retention | #662 | Owner-selected S3-compatible store | Platform owner | Scoped key round-trips list/put/get/delete; independent of the host |
| RPO/RTO acceptance and maintenance window | #662, #663 reporting | migration.md defaults plus owner decision | Platform owner | Missing decision blocks the restore gate |
| External monitoring destination | #663 | Owner-selected provider | Platform owner | Deliberate failure notifies the destination |
| GitHub plan capabilities for private-repo environments | #661 | GitHub plan settings | Platform owner | If unavailable, record as external blocker; do not simulate protection |
| Hetzner budget ceiling and location/server-type confirmation | #657+ VM tiers | P0 inventory and owner decision | Platform owner | Preview rejects over-budget intents per the P1-02 contract |
| GrowthBook/Unleash client traffic requirements | #658 endpoint decisions | Owning application teams | App owner | Documented endpoint list before restricting anything |

## 14. References

- [Dokploy installation](https://docs.dokploy.com/docs/core/installation) and [manual installation](https://docs.dokploy.com/docs/core/manual-installation): installer behaviour, ports, version pinning, update path, post-install hardening.
- [Dokploy Compose](https://docs.dokploy.com/docs/core/docker-compose): environment injection, bind mount and named volume rules, re-clone behaviour.
- [Dokploy Compose API](https://docs.dokploy.com/docs/api/compose) and [Deployment API](https://docs.dokploy.com/docs/api/deployment): endpoint and field shapes captured as fixtures.
- [Dokploy auto deploy](https://docs.dokploy.com/docs/core/auto-deploy): webhook and API triggers to disable for CI-owned units.
- [Dokploy backups](https://docs.dokploy.com/docs/core/backups) and [volume backups](https://docs.dokploy.com/docs/core/volume-backups): platform backup scope, S3 requirement, restore steps, named-volume-only rule.
- [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action): federated identity, tags, ephemeral nodes.
- [Tailscale HTTPS](https://tailscale.com/docs/how-to/set-up-https-certificates.md): 90-day certificates, manual renewal for file-based certs, CT ledger warning.
- [Hetzner firewall FAQ](https://docs.hetzner.com/cloud/firewalls/faq/): stateful behaviour and the private-network limitation.
- [Docker packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/): NAT diversion before ufw, DOCKER-USER.
- [SOPS usage](https://main.getsops.io/_print/docs/usage/): age identities, key files, updatekeys and rotate order on compromise.
- [GitHub OIDC](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-cloud-providers) and [managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments): protection rules and plan requirements.
- Repository contracts: [ADR 0001](../adr-0001-platform-ownership.md), [validation.md](../validation.md), [current-state.md](../current-state.md), [migration-runbook.md](../migration-runbook.md), [agent-execution.md](../agent-execution.md), [sources.md](../sources.md), [work-items.json](../work-items.json), [local-lab.md](../local-lab.md), [pulumi-hcloud.md](../pulumi-hcloud.md).
