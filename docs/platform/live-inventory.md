# Live inventory snapshot

**Gate:** G0 blocked. **Docker snapshot:** 2026-10-25T12:00:34Z. **Read-only host probes:** 2026-10-25T12:01:54Z. **Collector run:** `20261025T120034Z-4318e7a6`.

This is a sanitized snapshot of the selected Docker engine and repository service definitions. The engine is a source-host candidate, not an owner-confirmed production identity. No containers, volumes, networks, DNS records, credentials, or cloud resources were changed. Database probes below were read-only. The private normalized artifact is ignored at `.artifacts/platform/20261025T120034Z-4318e7a6/inventory.json`; it has directory mode `0700` and file mode `0600` and is not committed. No approved external evidence store was configured.

Repository service facts remain pinned to [`e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3`](https://github.com/AniTrend/local-stack/commit/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3). The collector ran from documentation commit `d7e0add6242b88d02443fb5ddb8ba584f23149e5` with an uncommitted worktree, so this is not a clean-candidate release record.

## Host and runtime

| **Observed** | **Value** |
| --- | --- |
| Docker context | `default`, local Unix endpoint |
| Docker client and server | `29.9.1` |
| Docker host OS and architecture | Pop!_OS 24.04 LTS, `x86_64` |
| Docker engine mode | Swarm inactive, not a Swarm manager |
| Host CPU and memory reported by Docker | 4 CPUs, 16,704,286,720 bytes |
| Container and volume counts | 34 containers total, 28 running, 22 local volumes |
| Repository service matches | 16 of 24 Compose service definitions |
| Other runtime containers | 18 unmatched to this repository; names are intentionally omitted |
| Collector-host systemd timers | 13 observed on the collector's host, not proof of the Docker engine host's jobs; unit names are private |
| Tailscale daemon | `tailscaled.service` active; ACLs and device grants not inspected |
| Doco-CD controller | `doco-cd.service` inactive; no Doco-CD container observed on this engine |
| Portainer | Container running; deployment authority was not verified |

`docker stack ls` is unavailable because this engine is not a Swarm manager. Compose labels identify service/project matches, not the person or controller that performs updates. The source `.doco-cd.yml` points at `dev` and enables reconciliation; that configuration is not evidence of a running controller. Portainer remains a possible controller because the authored service has Docker socket access.

The runtime query found no repository or selected-engine service named `anitrend-relations`. A backend on another host or outside this Docker context remains unknown.

## Repository-matched services

Docker `RepoDigests` are the observed image manifest identities. Resource usage is a single `docker stats --no-stream` sample at observation time, not a capacity test. `unknown` health means Docker reported no health state; it is not a pass. All 16 matched containers reported zero Docker memory and CPU limits.

All 16 observed images reported `linux/amd64`, matching the engine's `x86_64` architecture.

| Service | Runtime image | Observed digest | State / health | CPU / memory |
| --- | --- | --- | --- | --- |
| `beszel` | `henrygd/beszel:0.21.0` | `sha256:6b39a8b64f9b15d00a25e7683e31a93c46161182a54f62713525107064e10599` | running / unknown | 0.01% / 24 MiB |
| `beszel-agent` | `henrygd/beszel-agent-intel:0.21.0` | `sha256:4ca051605018b4877d438102bc975f46f8e9318c94a1afbdcb71f12107abe535` | running / unknown | 0.00% / 16 MiB |
| `grafana` | `grafana/grafana-oss:13.0.1` | `sha256:0f86bada30d65ef9d0183b90c1e2682ac92d53d95da8bed322b984ea78a4a73a` | running / unknown | 1.34% / 120 MiB |
| `growthbook` | `growthbook/growthbook:4.4.0` | `sha256:4e65f53c7fc11906f3346ba3b9d9b9f86a973c14e1139290a77f3b6d9a5e79ce` | running / healthy | 1.93% / 903 MiB |
| `growthbook-proxy` | `growthbook/proxy:v1.3.5` | `sha256:b698e9345aaa8ef264aedc71437035b340a37044977fddcc96794a8391a9fbb9` | running / unhealthy | 0.59% / 69 MiB |
| `loki` | `grafana/loki:3.7.2` | `sha256:191d4fdfb7264f16989f0a57f320872620a5a7c2ceeec6229212c4190ec49b86` | exited | not sampled |
| `memcached` | `memcached:1.6.41` | `sha256:f7a252e7ba3fbbe9672c483354c5081d02b780122c3bb97bd311d5662b54d0ad` | running / unknown | 0.02% / 1 MiB |
| `mongo` | `mongo:8.3.4` | `sha256:48a009d2d8007e92d6d7e8baa31713cd11c48c06e827e856240e5a1d319b49d9` | running / unknown | 1.37% / 125 MiB |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.152.1` | `sha256:fa1f6ea8dabd3042fabf4411eed7fa52f253edd8940140bec89a573e62a24eb7` | exited | not sampled |
| `portainer` | `portainer/portainer-ce:2.43.0` | `sha256:707366c811956fe077135a6633af67e698529612869711cdb24896c892b28feb` | running / unknown | 0.00% / 36 MiB |
| `postgres` | `postgres:18` | `sha256:f7ce845ee6873dd84be93c9828fe0d1fab0f9707dc9ac569694657398b290bce` | running / unknown | 0.00% / 23 MiB |
| `prometheus` | `prom/prometheus:v3.11.3` | `sha256:e4254400b85610324913f0dc4acf92603d9984e7519414c5a12811aa6146acc3` | restarting | not sampled |
| `redis` | `redis:8.6-alpine` | `sha256:d146f83b1e0f02fc27c26a50cee39338c736674c5959db84363e6ae3cd9e02d2` | running / unknown | 0.41% / 13 MiB |
| `tempo` | `grafana/tempo:2.10.5` | `sha256:ee21727732c7a7199cb71c3eee9153bbf23f9b0b87619f0555a0cf21a67f1a33` | exited | not sampled |
| `traefik` | `traefik:v3.7` | `sha256:6b9cbca6fac42ab0075f5437d8dc1685cfd188626d8d515839ea94f8b6271c42` | running / unknown | 0.14% / 94 MiB |
| `website` | `ghcr.io/anitrend/website:0.4.2` | `sha256:4ec9c3d27c0f21b0211895a47052e34ffe5a2cc7a33ab2410e36f57eabc21d92` | running / unknown | 0.00% / 9 MiB |

The 8 repository service definitions not observed on this engine are `apisix_dashboard`, `apisix_gateway`, `etcd`, `local-stack-deployer`, `doco-cd`, `edge-graphql`, `anitrend-edge`, and `unleash`. This means not observed on the selected engine, not proven absent from every host.

Several runtime tags differ from the pinned repository snapshot, including GrowthBook, GrowthBook Proxy, MongoDB, Redis, Grafana, Loki, OpenTelemetry Collector, Prometheus, Tempo, Portainer, Memcached, and the Beszel agent image variant. No image upgrade or service repair was performed as part of phase 0.

## Data and persistence observations

| Service | Read-only runtime evidence | Storage observation | Migration constraint |
| --- | --- | --- | --- |
| PostgreSQL | `18.4 (Debian 18.4-1.pgdg13+1)`; data directory `/var/lib/postgresql/18/docker` | `postgres-data`, mounted at `/var/lib/postgresql`, measured at 209,700,000 bytes | Keep PostgreSQL 18. The source Compose comment still describes a PG17 layout and declares `/var/lib/postgresql/data`; actual server data directory and mount differ from that comment/source path. No restore was run. |
| MongoDB | `mongod --version` reports `8.3.4`, `x86_64` | `mongo_mongo-data`, measured at 744,800,000 bytes, mounted at `/data`, `/data/configdb`, and `/data/db` | The source snapshot declares only `/data/configdb` and `/data/db`. Runtime topology needs owner review and a tested database-aware restore. |
| Redis | `redis-server` reports `8.6.3`; `CONFIG GET` reports `appendonly=yes`, `dir=/data`, `dbfilename=dump.rdb` | No Docker mount observed for the Redis container | **Inferred:** AOF data is in the container writable layer and may be lost when the container is removed. Do not classify Redis as disposable cache until the writer/data owner confirms. |

The inspected database values and mount metadata are configuration/runtime facts only. No database rows, keys, credentials, or raw process environments were read or committed.

## Network and health boundary

| Service | Host binding observed |
| --- | --- |
| `traefik` | TCP 80 and 443, wildcard IPv4 and IPv6 |
| `mongo` | TCP 27017, wildcard IPv4 and IPv6 |
| `postgres` | TCP 5432, wildcard IPv4 and IPv6 |
| `redis` | TCP 6379, wildcard IPv4 and IPv6 |

Wildcard bindings establish Docker host-port publication, not internet reachability. No outside-tailnet, Host/SNI, direct-port, or IPv6 probe was run. They are required before any private-ingress gate can pass. The observed unhealthy GrowthBook Proxy, restarting Prometheus, and exited Loki, OTel Collector, and Tempo were left unchanged.

## Phase 0 decisions and blockers

The collector records 24 repository service units, 18 unmatched runtime containers, per-service `unresolved` dispositions, and a schema-valid production environment contract with 37 unresolved inputs. Each service record has explicit fields for source identity, disposition, owner, ingress, health, configuration/secret references, dependencies, mounts, database facts, writer/job mapping, external dependencies, backup/restore method, and runtime evidence. The contract schemas are `infra/pulumi/shared/inventory.schema.json` and `infra/pulumi/shared/environment.schema.json`.

G0 remains blocked. The source host role, runtime source commit, per-service owners and freeze procedures, writer/job schedule, external API providers, database backup/restore paths, APISIX route/consumer/plugin export, Hetzner project/location/server type, DNS provider/zone/records/TTL, private hostnames/certificate strategy, Tailscale grants, Pulumi backend, backup destination/retention/recovery references, RPO/RTO, maintenance window, downtime limit, and rollback thresholds lack owner-backed evidence. The selected engine does not run APISIX, so its live policy export is unavailable here. No service has a final migration disposition.

The required inventory targets ran with an isolated interpreter installed from `tools/requirements.txt`:

```sh
make PYTHON=/tmp/omp-platform-inventory-653-testenv/bin/python platform-inventory ENV=legacy
make PYTHON=/tmp/omp-platform-inventory-653-testenv/bin/python platform-inventory-validate ENV=legacy
/tmp/omp-platform-inventory-653-testenv/bin/python -m pytest -q tests/platform/test_inventory.py
```

Results: `schema=valid reconciliation=blocked`, `schema=valid gate=blocked`, and the complete inventory test file passed 6 tests. The system `python3` lacks PyYAML and jsonschema; install the documented tool requirements before using Make with its default interpreter.

Read-only host probes:

```sh
docker exec --user postgres postgres sh -c 'exec psql --no-psqlrc --tuples-only --no-align --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="${POSTGRES_DB:-$POSTGRES_USER}" --command="BEGIN READ ONLY; SHOW server_version; SHOW data_directory; COMMIT;"'
docker exec mongo mongod --version
docker exec redis redis-server --version
docker exec redis redis-cli --raw CONFIG GET appendonly dir dbfilename
systemctl is-active doco-cd.service
systemctl is-active tailscaled.service
```

The PostgreSQL query at 2026-10-25T12:01:54Z returned version 18.4 and `/var/lib/postgresql/18/docker`; MongoDB and Redis returned 8.3.4 and 8.6.3. Redis reported AOF enabled, directory `/data`, and `dump.rdb` filename. The Doco-CD unit was inactive and Tailscale active at that probe time.

The automated collector uses a synthetic Docker CLI fixture in tests. The selected real Docker engine has active workloads, so no disposable Docker engine was designated for the phase-0 fixture acceptance check. External Host/SNI, direct-port, and IPv6 probes, backup/restore, cloud provisioning, and cutover were not run. This report does not claim those gates passed.

## Collector publication checks

The collector draft was checked again before publication on 2026-10-27 without changing the historical observations above. The inventory regression file passed 6 tests under the existing isolated platform Python environment. A new explicit `ENV=lab DOCKER_CONTEXT=default` read-only collection produced run `20261027T183959Z-fcf5c1ad`; schema validation returned `schema=valid gate=blocked`. The private JSON remains ignored. This later lab collection is not a new production inventory, does not resolve G0, and did not mutate the Docker daemon.

The CI `Platform inventory validation` job runs the synthetic Docker CLI regression suite with read-only repository permissions and no cloud credentials. The real disposable-engine fixture acceptance and owner-backed live reconciliation still remain to be performed.

Review repairs added direct reconciliation regressions and realistic Docker/systemd formats. The complete platform inventory suite now passes 30 tests. Running the new semantic/normalization regressions against the published pre-repair collector `a094dbf` produced 23 failures and one passing semantic control. The repaired collector rejects waived required production inputs, disallowed contexts, missing/duplicate/inconsistent container mappings, unresolved ownership, and missing confirmed database/health facts.

The repaired read-only collector produced lab run `20261027T192226Z-bf4b5c69`; schema validation again returned `schema=valid gate=blocked`. Timer observations now use `collector_host_timers` with explicit collector provenance, integer-microsecond timestamps become UTC ISO 8601 strings, unavailable timestamps remain null, and Docker's numeric-string volume reference counts are preserved. Older private artifacts carrying the previous timer field must be recollected, not edited into passing evidence.
