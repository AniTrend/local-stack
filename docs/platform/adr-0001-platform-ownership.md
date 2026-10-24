# ADR 0001 Platform ownership and migration defaults

Status: proposed implementation baseline, to become accepted through review of the plan PR. Scope: AniTrend private platform. Date: 2026-10-24.

## Decision and reason

Use Pulumi TypeScript with @pulumi/hcloud for cloud resources; small Ansible roles for the host; Dokploy for application operations; GitHub Actions for verification/promotion; Tailscale for private access. This removes routine interactive deployment work while keeping the existing container service definitions useful.

The important constraint is one owner per resource. Doco-CD and Dokploy may coexist only across explicitly separate legacy and target resources. Pulumi does not deploy application containers to the Dokploy host. Ansible does not periodically reapply application Compose files.

| Object | Owner | Source of intent |
|---|---|---|
| Hetzner VM, private network, firewall, attached volume | Pulumi hcloud program | Versioned non-secret environment configuration |
| Public DNS | Pulumi provider for the confirmed authoritative DNS service | Explicit zone/record configuration |
| OS users/packages, mounts, SSH, host firewall, Tailscale | Ansible | Inventory contract + host roles |
| Dokploy installation/upgrade | Ansible invokes the supported pinned lifecycle | Version lock and bootstrap role |
| Dokploy Docker/Swarm/Traefik topology | Dokploy's supported setup | Tested release and supported configuration |
| Application deployment unit | Dokploy | Release bundle derived from service-local sources |
| App secrets | SOPS+age source, delivered by CI/API adapter | Existing encrypted dotenv files and scoped recovery keys |
| Cloud/backend/API credentials | Selected secured CI/backend secret store | Credential references, never plaintext Git |
| Release selection and promotion | GitHub Actions | Commit, image digests, config hash and passed checks |
| Doco-CD/old Portainer ownership | Legacy host only until retirement | Frozen legacy runbook |
| Local disposable fixtures | Pulumi Docker/Molecule | Lab state and unique run labels |

## Deployment topology and modes

Start with one new target VM hosting Dokploy and the workloads. Build application images in their owning CI pipelines and pull immutable images on the target. Do not add a management VM, load balancer or HA cluster until measured constraints justify them. Independent remote servers are a later scaling option; they do not automatically replicate application data.

Default migrated workload units to Dokploy Compose on the single host. Dokploy itself may use Swarm internally; that does not imply application HA. The adapter must preserve the effective resource limits, network aliases, health/restart policy and volume identities previously supplied by Swarm fragments. A proven need for Dokploy Stack mode must be recorded per unit with tests and an ADR/catalog update; there is no implicit loss of Swarm semantics.

Use a fresh VM to avoid installing Dokploy over the existing Traefik and data paths. The old host remains the rollback source. Default to the observed production architecture; check every pinned image/tool for native support. Choosing another architecture requires a documented compatibility decision, not silent production emulation.

## Configuration and repository layout

Retain service-local Compose/config files as the authored application sources. Add only target-specific overrides and a deterministic adapter. Generated release artifacts are outputs, not a second maintained source. Legacy stacks remain generated until no retained workflow needs them.

Proposed new paths, absent at the baseline:

- `infra/pulumi/shared/`: environment and inventory types/validation.
- `infra/pulumi/docker/`: disposable local fixture resources.
- `infra/pulumi/hcloud/`: actual cloud resources.
- `ansible/`: baseline/bootstrap roles, inventory adapter and Molecule scenarios.
- `deploy/dokploy/`: API adapter, unit catalog and target overrides.
- `tests/platform/`: fixtures, integration and negative-path tests.
- `tools/platform/`: small scripts behind documented Make targets.
- `docs/platform/`: decisions, contracts and operations.
- `.artifacts/platform/`: ignored non-secret runtime evidence; secret-bearing evidence is stored separately.

Use one logical environment contract with separate provider implementations. Docker containers are not Hetzner VM emulators. Share validated intent and output schemas, not an abstraction that pretends cloud firewalls/volumes/systemd were tested by Docker.

## State and secrets

Default production infrastructure state to Pulumi Cloud to avoid operating another state service. If account policy or cost prevents that, record a reviewed external object-store backend with encryption, locking/access controls, independent recovery and a restore test. Never keep the only production state copy on the server being replaced. Local lab state is separate and disposable.

Retain SOPS+age for this migration. Decrypt only selected service/environment values in the trusted delivery path and inject them through the tested API. Dokploy and container runtime may retain secret-bearing configuration; protect their state/backups accordingly. Source cleanup does not imply those runtime copies vanished.

No secret-manager migration is bundled. A later native external-secret integration can replace the adapter only through a new ADR and rotation/recovery evidence. Avoid self-hosting a secret authority that cannot be bootstrapped during a total platform outage.

## Ingress and access

Public application routing and private administrative routing are separate. Public services are an explicit inventory-derived allowlist. Private includes Dokploy, gateway administration, Grafana, Traefik dashboard and feature-management administration. Databases and telemetry ingestion stay on scoped internal networks.

Private DNS alone is not a security boundary. Validate the listener/firewall/proxy arrangement with public-IP Host/SNI probes, unauthorized tailnet probes, direct ports and IPv6. Hetzner Cloud Firewalls do not filter private-network traffic and Docker port publication can bypass ordinary ufw expectations.

Do not advertise every Docker subnet to the tailnet by default. Give operators and CI narrowly scoped access. Use TLS and a renewable certificate strategy for private endpoints. Split feature-management administration from SDK/proxy/webhook delivery according to actual client requirements.

## Delivery and risk policy

Use immutable image digests and a versioned bundle/config hash. CI promotes a tested release through Dokploy's private API and confirms the effective deployment. Disable competing auto-deploy triggers for CI-owned units. Dokploy is event-driven deployment management, not assumed continuous GitOps drift reconciliation.

Preserve deterministic Renovate/OpenCode checks. Low-risk eligible dependency updates may follow the existing merge policy after tests; major/stateful/infra/workflow/secrets/network changes and unknown risk require the existing manual promotion path. A merged branch or AI approval is not itself evidence of a successful deployment.

SOPS source, Pulumi state, Dokploy registry and release records have different roles; none should silently overwrite another's authority. API reconciliation must be idempotent and fail on ambiguous ownership.

## Gateway decision

Keep APISIX+etcd during the core migration; export and test its actual configuration. Later evaluate APISIX file-driven standalone first. Evaluate Kong only against requirements and measured operator benefit. Kong DB-less limits Manager editing and decK sync; its official OIDC plugin requires Enterprise. Traefik remains Dokploy's ingress layer regardless of gateway choice.

## Alternatives intentionally deferred

k3s/Flux, multi-node HA, separate management hosts, new secret managers, native Dokploy Pulumi providers and an externally sold multi-tenant platform are not required. They need a separate requirement and cost/maintenance justification. Doco-CD remains a valid alternative deployment owner, but using it concurrently for Dokploy's applications is rejected.

## Revisit triggers

Revisit this ADR when single-host measured capacity/availability is inadequate, recovery targets cannot be met, necessary gateway features differ, or the platform must host untrusted external tenants. Record the triggering evidence and migration impact rather than adding tools pre-emptively.
