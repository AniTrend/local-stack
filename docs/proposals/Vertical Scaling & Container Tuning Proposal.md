# Vertical Scaling & Container Tuning Proposal

**Scope:** AniTrend/local-stack on Hetzner CAX11 (ARM64). Convert current Compose-based deployment to Swarm-friendly stacks, set sane resource limits, and tune observability-heavy services to reduce RAM and disk churn. This spec is actionable for both local single-node swarm and future 2-node expansion.

---
## 1) Executive Summary
- **Problem:** 4 GB RAM host runs ~70% memory, frequent disk churn from observability and gateways; risk of OOM and degraded IO.
- **Decision:** **Scale vertically to 8 GB first**, then apply **resource caps + retention/logging tuning**. Consider horizontal expansion only after limits/tuning and if HA/isolation are required.
- **Outcome:** Expected steady-state memory ~45–55%, significantly reduced write amplification, predictable performance, clear runway to add a second node with an LB and storage plan.

---
## 2) Current State (from `docker stats`)
Top RAM users:
- **growthbook** ≈ 775 MiB (20%)
- **tempo** ≈ 426 MiB (11%)
- Tier of ~120–190 MiB: traefik, grafana, prometheus, django-server, growthbook-proxy, anitrend-edge, apisix-gateway, otel-collector, mongo.

I/O profile:
- **High block IO writes** (50–180 GB written per service since start) across Prometheus, Loki, Tempo, Grafana, gateways, DBs.
- **High network IO** (OTel ~35 GB sent; GrowthBook ~33 GB received; Loki/Tempo/Grafana hundreds of MB–GB).

Implication: Primary risk is **storage churn**; RAM pressure is secondary but real.

---
## 3) Target Architecture Snapshot
- **Swarm mode (single node initially)** with modular stacks: `infrastructure`, `observability`, `platform`.
- **Shared overlay network**: `traefik-public` (external, attachable).
- **Named volumes**: retained for stateful services; rotation/logging tuned to reduce writes.
- **Deploy resources**: per-service **reservations** and **limits** to prevent runaway usage.

---
## 4) Global Host/Daemon Settings
- **Default logging driver** (reduce JSON log growth):
  ```json
  // /etc/docker/daemon.json
  {
    "log-driver": "local",
    "log-opts": { "max-size": "10m", "max-file": "3" }
  }
  ```
- **Filesystem mount options** for data volumes: prefer `noatime` on host mounts to lower metadata writes.
- **Swap safety net**: zram or a 1–2 GB swapfile. Keep service memory limits tight (swap is last resort).

---
## 5) Service-Level Limits & Tuning (Swarm `deploy`)
> The following are **starting points**. Adjust up/down based on telemetry. All examples assume Swarm v3 syntax.

### 5.1 Traefik (edge router)
- Rationale: modest RAM; avoid verbose access logs.
```yaml
services:
  traefik:
    image: traefik:v3.5
    command:
      - --accesslog=false
    deploy:
      mode: global
      placement:
        constraints: ["node.role == manager"]
      resources:
        reservations: { memory: "128M", cpus: "0.10" }
        limits:       { memory: "512M", cpus: "0.50" }
    logging:
      driver: local
      options: { max-size: "10m", max-file: "3" }
```

### 5.2 Prometheus
- Rationale: curtail churn; lean retention and query concurrency.
```yaml
  prometheus:
    image: prom/prometheus:v2.55.1
    command:
      - --storage.tsdb.retention.time=3d
      - --query.max-concurrency=10
    deploy:
      mode: replicated
      replicas: 1
      resources:
        reservations: { memory: "512M", cpus: "0.25" }
        limits:       { memory: "1200M", cpus: "0.80" }
    logging:
      driver: local
      options: { max-size: "10m", max-file: "3" }
```

Prometheus scrape strategy (config hints):
- Increase scrape intervals on non-critical targets to `30s`–`60s`.
- Drop high-cardinality labels and add recording rules for frequent queries.

### 5.3 Loki
- Rationale: balance memory vs index/chunk churn; enable retention.
```yaml
  loki:
    image: grafana/loki:2.9.0
    volumes: ["loki-data:/var/loki"]
    deploy:
      resources:
        reservations: { memory: "256M" }
        limits:       { memory: "800M" }
```
Loki config (excerpt):
```yaml
limits_config:
  retention_period: 72h
  ingestion_rate_mb: 4
  max_chunk_target_size: 1572864   # ~1.5 MiB
compactor:
  working_directory: /var/loki/compactor
  retention_enabled: true
```

### 5.4 Tempo
- Rationale: traces consume RAM/IO; tighten retention and concurrency.
```yaml
  tempo:
    image: grafana/tempo:2.6.0
    command:
      - -storage.trace.backend=local
      - -storage.trace.local.path=/var/tempo
      - -storage.trace.retention=48h
      - -distributor.log-received-traces=false
      - -ingester.max-traces-per-user=100000
    volumes: ["tempo-data:/var/tempo"]
    deploy:
      resources:
        reservations: { memory: "256M" }
        limits:       { memory: "600M" }
```

### 5.5 OpenTelemetry Collector
- Rationale: throttle to avoid bursts spilling into swap.
```yaml
  otel-collector:
    image: otel/opentelemetry-collector:0.99.0
    deploy:
      resources:
        reservations: { memory: "128M", cpus: "0.10" }
        limits:       { memory: "384M", cpus: "0.40" }
```

### 5.6 Grafana
```yaml
  grafana:
    image: grafana/grafana-oss:11.5.2
    deploy:
      resources:
        reservations: { memory: "128M" }
        limits:       { memory: "512M" }
    logging:
      driver: local
      options: { max-size: "10m", max-file: "3" }
```

### 5.7 GrowthBook (Dashboard)
- Rationale: top RAM user; cap Node heap.
```yaml
  growthbook:
    image: growthbook/growthbook:latest
    environment:
      - NODE_OPTIONS=--max-old-space-size=512
    deploy:
      resources:
        reservations: { memory: "256M", cpus: "0.20" }
        limits:       { memory: "800M", cpus: "0.80" }
    logging:
      driver: local
      options: { max-size: "10m", max-file: "3" }
```

### 5.8 GrowthBook Proxy
```yaml
  growthbook-proxy:
    image: growthbook/proxy:latest
    deploy:
      resources:
        reservations: { memory: "64M" }
        limits:       { memory: "256M" }
```

### 5.9 APISIX + etcd
- Rationale: cap workers/memory; ensure etcd compaction/quotas.
```yaml
  apisix-gateway:
    image: apache/apisix:3.9.1
    deploy:
      resources:
        reservations: { memory: "128M", cpus: "0.10" }
        limits:       { memory: "384M", cpus: "0.40" }

  apisix-etcd:
    image: bitnami/etcd:latest
    environment:
      - ETCD_AUTO_COMPACTION_RETENTION=1
      - ETCD_QUOTA_BACKEND_BYTES=4294967296   # 4 GiB
    deploy:
      resources:
        reservations: { memory: "64M" }
        limits:       { memory: "256M" }
```

### 5.10 Datastores (Mongo, Postgres, Redis, Memcached)
```yaml
  mongo:
    image: mongo:7
    deploy:
      resources:
        reservations: { memory: "256M" }
        limits:       { memory: "800M" }

  postgres:
    image: postgres:16
    deploy:
      resources:
        reservations: { memory: "128M" }
        limits:       { memory: "512M" }

  redis:
    image: redis:7
    deploy:
      resources:
        reservations: { memory: "32M" }
        limits:       { memory: "128M" }

  memcached:
    image: memcached:1.6
    command: ["-m", "64"]
    deploy:
      resources:
        reservations: { memory: "32M" }
        limits:       { memory: "96M" }
```

### 5.11 App Services (Django, anitrend-edge)
```yaml
  django-server:
    deploy:
      resources:
        reservations: { memory: "128M", cpus: "0.10" }
        limits:       { memory: "384M", cpus: "0.50" }

  anitrend-edge:
    deploy:
      resources:
        reservations: { memory: "128M", cpus: "0.10" }
        limits:       { memory: "384M", cpus: "0.50" }
```

---
## 6) Observability Tuning Checklist
- **Prometheus**: scrape intervals 30–60 s for low-priority jobs; retention 3–7 d; recording rules for expensive queries; drop high-card labels.
- **Loki**: enable retention; moderate chunk size; compactor concurrency capped; avoid logging noise at sources; use `local` driver with rotation.
- **Tempo**: retention 24–72 h unless needed longer; cap ingester limits; reduce exporter fanout.
- **Grafana**: disable auto-refresh on heavy dashboards by default; keep dashboard variables light.
- **OTel**: throttle batch sizes and queue depths to stay under memory limits; prefer gzip; reduce histograms if not needed.

---
## 7) Rollout Plan
1. **Upgrade VM to 8 GB RAM.**
2. **Apply daemon.json** logging settings; restart Docker.
3. **Deploy Swarm stacks** with the above `deploy.resources` limits and retention configs.
4. **Observe 24–72 h** under typical peak:
   - `container_memory_usage_bytes` vs limits
   - Disk writes/reads per service
   - Query latencies (Grafana/Prometheus)
5. **Tighten or relax** limits per service (+/− 128–256 MiB steps). Increase Prometheus/Loki/Tempo limits last.

---
## 8) Capacity & SLO Guardrails
- **Target steady-state RAM:** 45–55% on 8 GB.
- **Short spikes:** <75% for <5 min during deploys/backfills.
- **Disk writes:** keep per-day writes per service < size_of_volume / 30 to preserve SSD endurance.
- **Alerting:** warn at 70% container limit for 10 min; critical at 90% for 5 min; alert on node memory >80% for 15 min.

---
## 9) When to Add a Second Node
Add another CAX11 when you need **HA/maintenance freedom** or **workload isolation**.
- **Ingress:** Hetzner Load Balancer → Traefik (mode: global) on both nodes; or keepalived VIP.
- **Placement:** label a node `stateful=true` and **pin** DBs/APISIX/Loki/Tempo there.
- **Storage:** adopt Longhorn/Ceph if you need HA for persistent volumes; or accept single-writer model.
- **Replicas:** keep stateful at `replicas: 1`; scale stateless (Traefik, app APIs) as needed.

Example placement:
```yaml
deploy:
  placement:
    constraints:
      - node.labels.stateful == true
```

---
## 10) Risks & Mitigations
- **OOM from too-aggressive caps** → staged tuning (increase 128–256 MiB), swap cushion, alerts at 70/90% limit.
- **Data retention too short** → gradually increase retention after stability (watch disk usage growth).
- **Logging still chatty** → widen use of `local` driver, disable access logs in Traefik/APISIX unless debugging.
- **Future HA needs** → plan for LB + storage layer before adding node; document failover/runbooks.

---
## 11) Success Criteria
- Node memory steady at **≤55%** during regular load.
- 90th percentile dashboard loads **<2 s**; PromQL queries **<1 s** for common panels.
- Daily disk writes per service reduced by **30–50%** vs baseline.
- No OOM kills and no sustained swap activity (>5% active) over 7 days.

---
## 12) Appendix – Quick Snippets
**Create overlay network (once):**
```bash
docker network create --driver=overlay --attachable traefik-public
```

**Per-service logging override (if daemon default not changed):**
```yaml
logging:
  driver: local
  options:
    max-size: "10m"
    max-file: "3"
```

**Resource block template:**
```yaml
deploy:
  resources:
    reservations: { memory: "128M", cpus: "0.10" }
    limits:       { memory: "512M", cpus: "0.50" }
```

**Memcached memory cap via args:**
```yaml
command: ["-m", "64"]
```

---
**Next Actions:**
1) Upgrade to 8 GB; 2) apply daemon logging; 3) deploy tuned stacks; 4) observe & iterate; 5) revisit 2-node plan if needed.

