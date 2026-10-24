# Current state and live inventory contract

## Evidence boundary

This snapshot is repository evidence at [`e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3`](https://github.com/AniTrend/local-stack/commit/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3). It does not establish which services, images, volumes or controllers are live. P0-01 must reconcile the host before production choices are finalized.

The repository's default branch is `dev`. [AGENTS.md](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/AGENTS.md) makes service-local Compose/configuration authoritative and `stacks/` generated. [`.stackctl`](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/.stackctl) defines infrastructure, observability and platform stacks. The preferred `stackctl` CLI generates and checks stacks; `stackctl.sh` remains the Doco-CD compatibility path. `sync` validates drift and does not generate or deploy.

No repository issue templates, CONTRIBUTING file or inherited AniTrend/.github issue templates/contributing guide were present when reviewed. Use descriptive conventional titles, matching the existing repository's common style. Consult any newer rules before implementation.

## Service map from source and committed generated stacks

A source path ending in `.yaml` is intentional. Do not search only for `docker-compose.yml`. Images below are reviewed source tags, not recommendations to upgrade or proof of deployed versions. Resolve immutable digests and native architecture during implementation.

| Source directory / service keys | Source image(s) | Generated group | Migration concern |
|---|---|---|---|
| `traefik/`: traefik | traefik:v3.7 | infrastructure | Owns public 80/443; configuration bind mounts, certificate volume and Docker socket |
| `apisix/api-gateway/`: apisix_gateway | apache/apisix:3.18.0-debian | infrastructure | Runtime config uses etcd; cache volume; dynamic route inventory required |
| `apisix/api-dashboard/`: apisix_dashboard | apache/apisix-dashboard:3.0.1-alpine | infrastructure | Bind-mounted generated config; private administration |
| `apisix/etcd/`: etcd | bitnamilegacy/etcd:3.6.4 | infrastructure | Durable gateway configuration; snapshot/export and restore |
| `mongo/`: mongo | mongo:8.3.13 | infrastructure | Same volume mounted at /data/db and /data/configdb; inspect actual layout |
| `redis/`: redis | redis:8.10-alpine | infrastructure | AOF enabled without an explicit service data-volume mount |
| `portainer/`: portainer | portainer/portainer-ce:2.45.2 | infrastructure | Data volume and socket access; potential competing deployment owner |
| `observability/grafana/`: grafana | grafana/grafana-oss:13.0.2 | observability | State volume and provisioning bind mount |
| `observability/loki/`: loki | grafana/loki:3.7.8 | observability | Data volume and config bind mount |
| `observability/otel/`: otel-collector | otel/opentelemetry-collector-contrib:0.162.0 | observability | Config and service discovery; OTLP stays internal |
| `observability/prometheus/`: prometheus | prom/prometheus:v3.15.0 | observability | Data, alerts, config and old Swarm DNS targets |
| `observability/tempo/`: tempo, memcached | grafana/tempo:3.1.0; memcached:1.6.45 | observability | Trace data/config; memcached dependency |
| `beszel/`: beszel, beszel-agent | henrygd/beszel:0.21.0; henrygd/beszel-agent:0.21.0 | observability | Data/socket volumes and agent Docker socket access |
| `growthbook/dashboard/`: growthbook | growthbook/growthbook:5.1.0 | platform | Uploads, Mongo dependency, admin versus SDK/API traffic |
| `growthbook/proxy/`: growthbook_proxy | growthbook/proxy:v1.4.0 | platform | Validate client polling/streaming requirements before privatizing |
| `edge-graphql/`: edge-graphql | ghcr.io/anitrend/edge-graphql:0.1.16 | platform | Public API contract; no container healthcheck in source |
| `on-the-edge/`: anitrend-edge | ghcr.io/anitrend/on-the-edge:1.7.2 | platform | Source healthcheck commented out; dependent service/flag providers |
| `website/`: website | ghcr.io/anitrend/website:0.4.2 | platform | Public website if actually enabled |
| `postgres/`: postgres | postgres:18 | excluded: x-stack commented | Source comment says PG17/pre-18 data layout; actual data major is unknown |
| `unleash/`: unleash | unleashorg/unleash-server:8.2 | excluded: x-stack commented | Depends on a real database; do not activate from README alone |
| `doco-cd/`: doco-cd | ghcr.io/kimdre/doco-cd:0.127.0 | host-level, not generated | Polling controller with Docker socket and persistent state |
| `deploy/doco/local-stack-deployer/`: local-stack-deployer | local/local-stack-deployer:latest, built locally | separate runner | Fetches dev and calls compatibility wrapper through host socket |

See the [full baseline tree](https://github.com/AniTrend/local-stack/tree/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3) and the immutable [infrastructure](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/stacks/infrastructure.yml), [observability](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/stacks/observability.yml) and [platform](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/stacks/platform.yml) files. No `anitrend/` service source appears in this tree despite documentation mentioning it. Discover any live relations/backend service and its owning repository; do not invent a manifest from old prose.

## Confirmed source discrepancies to investigate

1. [PostgreSQL](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/postgres/docker-compose.yaml): image is 18, while the comment describes a PG17 volume and mounts /var/lib/postgresql/data. PostgreSQL 18 changes default storage paths. Determine the running major, PGDATA and volume contents before any start/restore; keep the actual major during migration.
2. [Mongo](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/mongo/docker-compose.yaml): two paths share one named volume. Closed #504 described an older three-mount state; its closure is not runtime proof of the current layout.
3. [Redis](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/redis/docker-compose.yaml): appendonly is enabled without an explicit volume mount. Determine whether an anonymous volume or a different live configuration holds durable state; do not label it a disposable cache without owner evidence.
4. [APISIX](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/apisix/api-gateway/config/apisix.yaml): despite the source filename, Compose mounts it as `conf/config.yaml`. It is runtime configuration using traditional/etcd mode, not a complete standalone route export. Enabled plugin names and the declared Loki global rule do not prove actual live policies.
5. [Traefik](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/traefik/config/traefik.yml): source uses the Docker provider and shared network defaults, while generated deployment is Swarm. Dashboard is disabled in source. Validate live provider, label placement and routing rather than assuming the dashboard is currently exposed.
6. [Doco runner](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/deploy/doco/local-stack-deployer/entrypoint.sh): secrets mode calls `secrets deploy` without the configured stack selector; the lock path is container-local. The Dockerfile installs neither sops nor age explicitly. It mounts a named workspace volume while controlling the host Docker daemon, so bind-mount path identity needs inspection. None of this proves the running image has those defects.
7. [CI](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/.github/workflows/ci.yml): semantic generation validation uses the CLI, while the dry-run/runner use the compatibility path. [CLI setup](https://github.com/AniTrend/local-stack/blob/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3/.github/actions/setup-stackctl/action.yml) explicitly supports Linux x86_64. Do not assume this covers the reported ARM64 host or local Mac.
8. Common Compose variables such as HOST/PORT are service-local. A combined Dokploy .env can change their meaning. Existing file mounts and stack-prefixed DNS require explicit conversion.

## Live inventory output

P0-01 creates `docs/platform/live-inventory.md` and a schema-validated private machine inventory. Every service record must include logical ID, disposition, source repository/path, actual image digest/architecture, host and runtime type, current/target deployment owner, dependencies, ingress class, health contract, configuration and secret references, volumes/data paths, database major/topology, writers/jobs, backup/restore method and observation time.

Required environment inputs: verified Hetzner project/location, target architecture/type, DNS provider/zone/records/TTL, private hostname/certificate approach, tailnet identity/grants, Pulumi state backend, backup destination and recovery credentials, RPO/RTO, maintenance window, maximum downtime and stop thresholds. Missing production inputs block the applicable gate. Synthetic lab values are allowed and must be visibly marked.

Raw docker inspect, process environments, APISIX consumer exports and database data can contain secrets. Store them only in restricted evidence storage. Commit sanitized facts and opaque evidence references, never raw dumps.

## Historical references

Closed issues [#475](https://github.com/AniTrend/local-stack/issues/475), [#500](https://github.com/AniTrend/local-stack/issues/500), [#503](https://github.com/AniTrend/local-stack/issues/503), [#504](https://github.com/AniTrend/local-stack/issues/504), [#505](https://github.com/AniTrend/local-stack/issues/505), [#533](https://github.com/AniTrend/local-stack/issues/533), [#534](https://github.com/AniTrend/local-stack/issues/534), [#535](https://github.com/AniTrend/local-stack/issues/535), [#536](https://github.com/AniTrend/local-stack/issues/536) and [#546](https://github.com/AniTrend/local-stack/issues/546) explain earlier Unleash, Swarm, rendering and deployment decisions. Reuse working code and tests; confirm current behaviour before duplicating or reviving old work.
