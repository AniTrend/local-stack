---
applyTo: **
description: This document provides an overview of the Local-Stack project, its structure, service configurations, common tasks, and best practices for local development infrastructure using Docker Compose.
---
## Project Overview
Local-Stack is a comprehensive local development infrastructure built with Docker Compose. It provides a collection of services commonly needed for application development including databases, API gateways, observability tools, reverse proxies, and more. This environment allows developers to run and test applications with a production-like infrastructure locally.

## Project Structure
The project is organized into directories, each containing docker-compose files for different services:

```
local-stack/
├── LICENSE
├── README.md
├── swarm.infrastructure.yml     # Docker Swarm configuration for infrastructure
├── swarm.observerability.yml    # Docker Swarm configuration for observability
├── anitrend/                    # AniTrend application specific configs
├── apisix/                      # API Gateway services
│   ├── api-dashboard/           # APISIX Dashboard
│   ├── api-gateway/             # APISIX Gateway
│   └── etcd/                    # etcd service for APISIX
├── growthbook/                  # Feature flag management
│   ├── dashboard/               # GrowthBook dashboard
│   └── proxy/                   # GrowthBook proxy
├── mongo/                       # MongoDB database
├── observability/               # Monitoring and observability services
│   ├── grafana/                 # Visualization and dashboards
│   ├── loki/                    # Log aggregation
│   ├── otel/                    # OpenTelemetry collector
│   ├── prometheus/              # Metrics collection and alerting
│   └── tempo/                   # Distributed tracing
├── on-the-edge/                 # Edge computing services
├── portainer/                   # Docker container management UI
├── postgres/                    # PostgreSQL database
├── redis/                       # Redis in-memory database
└── traefik/                     # Reverse proxy and edge router
    ├── auth/                    # Authentication configuration
    ├── certs/                   # SSL certificates
    └── config/                  # Traefik configuration
```

## Service Configuration

### Core Infrastructure

- **Traefik**: Acts as the main reverse proxy for all services
  - Configuration files: `traefik/config/traefik.yml` and `traefik/config/dynamic.yml`
  - Access: Default dashboard at `https://traefik.localhost`

- **Databases**:
  - **PostgreSQL**: Standard relational database
    - Configuration: `postgres/docker-compose.yaml`
    - Default port: 5432
  - **MongoDB**: Document database
    - Configuration: `mongo/docker-compose.yaml`
    - Default port: 27017
  - **Redis**: In-memory database
    - Configuration: `redis/docker-compose.yaml`
    - Default port: 6379

### API Gateway

- **APISIX**: API Gateway for managing APIs
  - Gateway configuration: `apisix/api-gateway/docker-compose.yml`
  - Dashboard configuration: `apisix/api-dashboard/docker-compose.yml`
  - Default access: `https://apisix.localhost`

### Observability Stack

- **Grafana**: Visualization dashboards
  - Configuration: `observability/grafana/docker-compose.yml`
  - Default access: `https://grafana.localhost`

- **Prometheus**: Metrics collection
  - Configuration: `observability/prometheus/docker-compose.yml`
  - Default access: `https://prometheus.localhost`

- **Loki**: Log aggregation
  - Configuration: `observability/loki/docker-compose.yml`

- **Tempo**: Distributed tracing
  - Configuration: `observability/tempo/docker-compose.yml`

- **OTel**: OpenTelemetry collector
  - Configuration: `observability/otel/docker-compose.yml`

### Management Tools

- **Portainer**: Docker container management
  - Configuration: `portainer/docker-compose.yml`
  - Default access: `https://portainer.localhost`

- **GrowthBook**: Feature flag management
  - Dashboard configuration: `growthbook/dashboard/docker-compose.yml`
  - Proxy configuration: `growthbook/proxy/docker-compose.yml`
  - Default access: `https://growthbook.localhost`

## Common Tasks

### Starting Services

Suggest appropriate commands to start services based on the developer's needs:

```bash
# Start the entire stack
docker-compose -f docker-compose.yml up -d

# Start specific services
cd postgres && docker-compose up -d
cd redis && docker-compose up -d
cd traefik && docker-compose up -d
```

### Setting Up Environment Variables

Help identify and create necessary `.env` files based on example files:

```bash
# For services that have .env.example files
cp .env.example .env
```

### Network Troubleshooting

Common issues include:
- Services unable to communicate with each other
- Port conflicts
- DNS resolution issues within Docker networks

Suggest commands to diagnose:
```bash
# Check network connectivity
docker network ls
docker network inspect traefik

# Check container logs
docker logs <container_name>

# Check container status
docker ps -a
```

### Accessing Services

All services are exposed through Traefik and accessible via subdomains:
- `https://traefik.localhost` - Traefik dashboard
- `https://grafana.localhost` - Grafana
- `https://prometheus.localhost` - Prometheus
- `https://apisix.localhost` - APISIX dashboard
- `https://portainer.localhost` - Portainer
- `https://growthbook.localhost` - GrowthBook

## Docker Swarm Deployment

The project includes Docker Swarm configuration files:
- `swarm.infrastructure.yml`: Core infrastructure services
- `swarm.observerability.yml`: Monitoring stack

Deployment commands:
```bash
# Initialize swarm
docker swarm init

# Deploy infrastructure stack
docker stack deploy -c swarm.infrastructure.yml infrastructure

# Deploy observability stack
docker stack deploy -c swarm.observerability.yml observability
```

## Best Practices

- Always use environment variables for sensitive information
- Use Docker volumes for persistent data storage
- Check container health status with `docker ps` and container logs
- Use the Portainer UI for visual container management
- Configure proper resource limits in Docker Compose files

## Common Issues and Solutions

1. **DNS Resolution**: Add proper DNS entries to `/etc/hosts` for local development
2. **SSL Certificates**: Generate self-signed certificates for development
3. **Service Startup Order**: Use `depends_on` in Docker Compose for dependent services
4. **Data Persistence**: Configure volumes properly to prevent data loss

## License

This project is licensed under the Apache License 2.0. Respect the license terms when modifying or redistributing the code.
