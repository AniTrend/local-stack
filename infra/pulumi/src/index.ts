import * as pulumi from "@pulumi/pulumi";
import * as command from "@pulumi/command";
import * as path from "path";

/**
 * This Pulumi stack orchestrates your existing docker-compose and swarm files using
 * Pulumi's Command provider. It does NOT replace your compose files yet, enabling
 * quick adoption and centralized lifecycle (preview, up, destroy).
 *
 * Modes:
 * - mode=compose (default): run targeted docker compose up -d for each service group.
 * - mode=swarm: deploy provided swarm YAMLs using docker stack deploy.
 *
 * Config keys (pulumi config set <key> <value>):
 * - local-stack:mode = compose | swarm
 * - local-stack:composeServices = ["postgres","mongo","redis","traefik","apisix","observability","growthbook","portainer"]
 */

const config = new pulumi.Config();
const mode = config.get("mode") || "compose"; // compose | swarm

// Root dir relative to this Pulumi program location
const root = pulumi.getProject();

// Service groups map to paths with compose files
const groups: Record<string, { cwd: string; file?: string | string[] }> = {
  postgres: { cwd: "../../postgres" , file: "docker-compose.yaml"},
  mongo: { cwd: "../../mongo", file: "docker-compose.yaml" },
  redis: { cwd: "../../redis", file: "docker-compose.yaml" },
  traefik: { cwd: "../../traefik", file: "docker-compose.yml" },
  apisixEtcd: { cwd: "../../apisix/etcd", file: "docker-compose.yml" },
  apisixGateway: { cwd: "../../apisix/api-gateway", file: "docker-compose.yml" },
  apisixDashboard: { cwd: "../../apisix/api-dashboard", file: "docker-compose.yml" },
  grafana: { cwd: "../../observability/grafana", file: "docker-compose.yml" },
  prometheus: { cwd: "../../observability/prometheus", file: "docker-compose.yml" },
  loki: { cwd: "../../observability/loki", file: "docker-compose.yml" },
  tempo: { cwd: "../../observability/tempo", file: "docker-compose.yml" },
  otel: { cwd: "../../observability/otel", file: "docker-compose.yml" },
  growthbookDashboard: { cwd: "../../growthbook/dashboard", file: "docker-compose.yml" },
  growthbookProxy: { cwd: "../../growthbook/proxy", file: "docker-compose.yml" },
  portainer: { cwd: "../../portainer", file: "docker-compose.yml" },
  anitrend: { cwd: "../../anitrend", file: "docker-compose.yml" },
  beszel: { cwd: "../../beszel", file: "docker-compose.yml" },
  onTheEdge: { cwd: "../../on-the-edge", file: "docker-compose.yaml" },
  // Umbrella compose files (not enabled by default to avoid duplication):
  observabilityAll: { cwd: "../../observability", file: "docker-compose.yml" },
  apisixAll: { cwd: "../../apisix", file: "docker-compose.yml" },
  growthbookAll: { cwd: "../../growthbook", file: "docker.compose.yml" },
};

const selected = (config.getObject("composeServices") as string[] | undefined) || Object.keys(groups);

if (mode === "compose") {
  // Bring up networks that are external in compose (e.g., traefik)
  const ensureTraefikNetwork = new command.local.Command("ensure-traefik-network", {
    create: "docker network inspect traefik >/dev/null 2>&1 || docker network create traefik",
    delete: "docker network rm traefik || true",
  });

  for (const name of selected) {
    const g = groups[name];
    if (!g) continue;
    const composeFileArg = g.file ? (Array.isArray(g.file) ? g.file.map(f => `-f ${f}`).join(" ") : `-f ${g.file}`) : "";
  const up = new command.local.Command(`compose-up-${name}` , {
      create: `docker compose ${composeFileArg} up -d`,
      delete: `docker compose ${composeFileArg} down`,
      dir: g.cwd,
    }, { dependsOn: [ensureTraefikNetwork] });
  }
}

if (mode === "swarm") {
  // Orchestrate Docker Swarm directly (no YAML)
  // Requires: docker swarm init (done automatically below)

  const get = (k: string, d?: string) => config.get(k) ?? d ?? "";

  const projectRoot = path.resolve(__dirname, "..", "..", "..");
  const abs = (...segments: string[]) => path.resolve(projectRoot, ...segments);

  const init = new command.local.Command("swarm-init", {
    create: "docker info | grep -q 'Swarm: active' || docker swarm init",
    delete: "echo 'Manual: docker swarm leave --force'",
  });

  // Ensure overlay network used by services exists
  const ensureOverlayTraefik = new command.local.Command("swarm-overlay-traefik", {
    create: "docker network inspect traefik >/dev/null 2>&1 || docker network create -d overlay traefik",
    delete: "docker network rm traefik || true",
  }, { dependsOn: [init] });

  // Volumes used by services
  const vTraefikCerts = new command.local.Command("vol-traefik-certs", {
    create: "docker volume inspect traefik_traefik-ssl-certs >/dev/null 2>&1 || docker volume create traefik_traefik-ssl-certs",
    delete: "docker volume rm traefik_traefik-ssl-certs || true",
  }, { dependsOn: [init] });

  const vPostgres = new command.local.Command("vol-postgres-data", {
    create: "docker volume inspect postgres-data >/dev/null 2>&1 || docker volume create postgres-data",
    delete: "docker volume rm postgres-data || true",
  }, { dependsOn: [init] });

  // Traefik service (ports, mounts)
  const traefikDir = abs("traefik");
  const traefikCreate = [
    "docker service create",
    "--name traefik",
    "--network traefik",
    "--publish published=80,target=80",
    "--publish published=443,target=443",
    `--mount type=volume,source=traefik_traefik-ssl-certs,destination=/etc/traefik/certs`,
    `--mount type=bind,src=${abs("traefik","auth","htpasswd")},dst=/etc/htpasswd,readonly`,
    `--mount type=bind,src=${abs("traefik","config","traefik.yml")},dst=/etc/traefik/traefik.yml,readonly`,
    `--mount type=bind,src=${abs("traefik","config","dynamic.yml")},dst=/etc/traefik/dynamic.yml,readonly`,
    `--mount type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock,readonly`,
    "traefik:v3.5",
  ].join(" ");

  const traefikSvc = new command.local.Command("swarm-svc-traefik", {
    create: traefikCreate,
    delete: "docker service rm traefik || true",
  }, { dependsOn: [ensureOverlayTraefik, vTraefikCerts] });

  // Postgres service (env + volume + network + optional traefik tcp labels)
  const pgUser = get("postgres:user", "postgres");
  const pgPass = get("postgres:password", "postgres");
  const pgDb = get("postgres:database", "postgres");
  const pgPort = get("postgres:port", "5432");
  const pgHost = get("postgres:host", "postgres.localhost");
  const certResolver = get("traefik:certResolver", "letsencrypt");
  const traefikEnable = get("traefik:enable", "true");

  const pgLabels = [
    `--label traefik.enable=${traefikEnable}`,
    `--label traefik.tcp.routers.postgres.rule=HostSNI(\`${pgHost}\`)`,
    `--label traefik.tcp.routers.postgres.entrypoints=websecure` ,
    `--label traefik.tcp.routers.postgres.service=postgres`,
    `--label traefik.tcp.routers.postgres.tls=true`,
    `--label traefik.tcp.routers.postgres.tls.certresolver=${certResolver}`,
    `--label traefik.tcp.services.postgres.loadbalancer.server.port=${pgPort}`,
  ].join(" ");

  const pgCreate = [
    "docker service create",
    "--name postgres",
    "--network traefik",
    `--mount type=volume,source=postgres-data,destination=/var/lib/postgresql/data`,
    `--env POSTGRES_USER=${pgUser}`,
    `--env POSTGRES_PASSWORD=${pgPass}`,
    `--env POSTGRES_DB=${pgDb}`,
    pgLabels,
    "postgres:17",
  ].join(" ");

  const pgSvc = new command.local.Command("swarm-svc-postgres", {
    create: pgCreate,
    delete: "docker service rm postgres || true",
  }, { dependsOn: [ensureOverlayTraefik, vPostgres] });
}

export const deploymentMode = mode;
