# AniTrend Local Stack

A local development environment for the AniTrend stack, providing a complete infrastructure setup for development and testing.

> Swarm migration: This repository has migrated from multiple per-service Docker Compose files to modular Docker Swarm stacks located under `stacks/`.
> Prefer the Swarm workflow for full environment deploys; per-service Compose remains for local iterative work.
>
> Quick start (Swarm): see `stacks/README.md` for the runbook (init swarm, create `traefik-public`, deploy `infrastructure`, `observability`, `platform`).

## Stack Components

### Gateway & Routing

- **APISIX Gateway**
  - API Gateway for managing endpoints
  - Traffic management and routing
  - Rate limiting and security policies

- **Traefik**
  - Edge router and reverse proxy
  - TLS termination
  - Service discovery
  - Load balancing

### Databases

- **PostgreSQL**
  - Primary relational database
  - Persistent data storage
  - Transaction support

- **MongoDB**
  - Document database
  - Flexible schema storage
  - High-performance queries

- **Redis**
  - In-memory data store
  - Caching layer
  - Session management

### Feature Management

- **GrowthBook**
  - Feature flag management
  - A/B testing
  - Feature experimentation

### Container Management

- **Portainer**
  - Container management UI
  - Stack deployment
  - Resource monitoring

## Observability Stack

The observability stack provides full monitoring capabilities through metrics, logs, and traces using the LGTM stack (Loki, Grafana, Tempo, Mimir/Prometheus) with OpenTelemetry for data collection.

### Components

#### Data Collection

- **OpenTelemetry Collector**
  - Collects metrics, logs, and traces
  - Exposes ports:
    - 4317: OTLP gRPC receiver
    - 4318: OTLP HTTP receiver
    - 8888: Internal metrics
    - 8889: Prometheus metrics
    - 13133: Health check

#### Metrics

- **Prometheus**
  - Metrics collection and storage
  - Retention: 512MB
  - Scrapes metrics from:
    - OpenTelemetry Collector
    - Tempo
    - Loki
    - Traefik
    - APISIX Gateway

#### Logs

- **Loki**
  - Log aggregation and storage
  - Integrated with Tempo for trace correlation

#### Traces

- **Tempo**
  - Distributed tracing backend
  - Integrates with Prometheus for metrics correlation
  - Integrates with Loki for log correlation

#### Visualization

- **Grafana**
  - Main visualization platform
  - Pre-configured data sources:
    - Prometheus for metrics
    - Loki for logs
    - Tempo for traces
  - Features enabled:
    - Trace to logs correlation
    - Trace to metrics correlation
    - Service graph visualization

### APISIX Logging to Grafana (Loki)

APISIX request/response logs are forwarded directly to Loki using the `loki-logger` plugin configured as a global rule in `apisix/api-gateway/config/apisix.yaml` (`global_rules`). Each request generates a structured JSON log line labeled with:

- `job=apisix`
- `service` (value from `OTEL_SERVICE_NAME`)
- `env` (deployment environment)
- `host` (gateway container hostname)
- `route` (APISIX route id, if matched)

The custom `log_format` includes trace and span IDs so you can pivot between traces (Tempo) and logs (Loki) in Grafana.

#### Query Examples (Grafana Explore > Loki)

```
{job="apisix"}
{job="apisix", status="500"}
{job="apisix", route="test-anything"}
{job="apisix"} |= "trace_id"
```

If you need the full original APISIX log body (request/response objects), remove or comment out the `log_format` section in the global rule to let the plugin emit the default verbose JSON.

#### Including Bodies (Optional)
You can toggle:
```
include_req_body: true
include_resp_body: true
```
Body capture increases memory usage and may omit very large bodies due to Nginx limits—enable only for debugging and consider `include_req_body_expr` filters.

#### Troubleshooting
1. No logs: Check `docker logs apisix-gateway | grep loki` for batch processor errors.
2. Connection issues: Ensure `loki` service is running and resolvable inside the `traefik` network.
3. Labels missing: Verify `global_rules` block loaded (container restart or config reload may be required).
4. Trace correlation missing: Confirm `set_ngx_var: true` under `plugin_attr.opentelemetry` and that the gateway was restarted after change.

#### Disable or Adjust
Edit `apisix/api-gateway/config/apisix.yaml` and modify or remove the `global_rules` entry with id `loki-all`, then recreate the APISIX container.


### Security

- TLS encryption via Traefik
- SSO authentication for exposed endpoints
- Grafana built-in authentication
- Internal-only access for Loki and Tempo

### Monitoring

The stack includes pre-configured alerts for:

#### Observability Stack Health

- Prometheus target availability
- OpenTelemetry Collector performance
- Loki request errors and memory usage
- Tempo trace ingestion

#### Infrastructure Monitoring

- API Gateway error rates (APISIX)
- Traefik error rates
- Resource usage (CPU, Memory, Disk)

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-org/local-stack.git
cd local-stack
```

### 2. Deploy via Swarm (recommended)

See `stacks/README.md` for the full runbook or use `stackctl.sh` helpers:

```bash
./stackctl.sh doctor --fix-network
./stackctl.sh up
```

### 3. Set up core infrastructure (Compose - legacy local-only)

```bash
# Start Traefik first
cd traefik
cp .env.example .env
docker-compose up -d

# Start databases
cd ../postgres && docker-compose up -d
cd ../mongo && docker-compose up -d
cd ../redis && docker-compose up -d
```

### 4. Set up the observability stack (Compose - legacy local-only)

```bash
cd ../observability
for dir in grafana prometheus loki tempo otel; do
  cp $dir/.env.example $dir/.env
done
docker-compose up -d
```

### 5. Set up additional services (Compose - legacy local-only)

```bash
# API Gateway
cd ../apisix
cp .env.example .env
docker-compose up -d

# Feature flags
cd ../growthbook
cp dashboard/.env.example dashboard/.env
cp proxy/.env.example proxy/.env
docker-compose -f docker.compose.yml up -d

# Container management
cd ../portainer
docker-compose up -d
```

### 5. Access the services

- Grafana: <https://grafana.your-domain.com>
- Prometheus: <https://prometheus.your-domain.com>
- APISIX Dashboard: <https://apisix.your-domain.com>
- Portainer: <https://portainer.your-domain.com>
- GrowthBook: <https://growthbook.your-domain.com>

## Project Structure

```sh
local-stack/
├── apisix/           # API Gateway configuration
├── anitrend/         # AniTrend application specific configs
├── edge-graphql/     # GraphQL gateway for edge services
├── growthbook/       # Feature flag management
├── mongo/           # MongoDB configuration
├── observability/   # Monitoring stack (detailed above)
├── on-the-edge/     # Edge computing configurations
├── portainer/       # Container management
├── postgres/        # PostgreSQL configuration
├── redis/          # Redis configuration
└── traefik/        # Reverse proxy router configuration
```

## Configuration

Each component has its own environment file for configuration. Copy the example files and modify as needed:

```sh
find . -name ".env.example" -exec sh -c 'cp "$1" "${1%.example}"' _ {} \;
```

## License

```txt
Copyright 2024 AniTrend

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
