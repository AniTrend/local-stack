# AniTrend Local Stack

A local development environment for the AniTrend stack, providing a complete infrastructure setup for development and testing.

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

1. Clone the repository:
```bash
git clone https://github.com/your-org/local-stack.git
cd local-stack
```

2. Set up core infrastructure:
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

3. Set up the observability stack:
```bash
cd ../observability
for dir in grafana prometheus loki tempo otel; do
  cp $dir/.env.example $dir/.env
done
docker-compose up -d
```

4. Set up additional services:
```bash
# API Gateway
cd ../apisix
cp .env.example .env
docker-compose up -d

# Feature flags
cd ../growthbook
cp .env.example .env
docker-compose up -d

# Container management
cd ../portainer
docker-compose up -d
```

5. Access the services:
- Grafana: https://grafana.your-domain.com
- Prometheus: https://prometheus.your-domain.com
- APISIX Dashboard: https://apisix.your-domain.com
- Portainer: https://portainer.your-domain.com
- GrowthBook: https://growthbook.your-domain.com

## Project Structure
```
local-stack/
├── apisix/           # API Gateway configuration
├── anitrend/         # AniTrend application specific configs
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
```bash
find . -name ".env.example" -exec sh -c 'cp "$1" "${1%.example}"' _ {} \;
```

## License

```
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
