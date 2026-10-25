import * as docker from "@pulumi/docker";
import * as pulumi from "@pulumi/pulumi";
import imageLock from "./images.lock.json";
import type { LabImagePlatform, LabIntent, LabOutputs } from "../shared/lab-contracts";

const ARCHITECTURE_PLATFORMS: Record<string, LabImagePlatform> = {
  amd64: "linux/amd64",
  x86_64: "linux/amd64",
  arm64: "linux/arm64",
  aarch64: "linux/arm64",
};
const RESERVED_CONTEXT = /(^|[-_.])(prod(?:uction)?|legacy|rehearsal|hcloud|hetzner|remote)(?:$|[-_.])/i;
const RUN_ID_PATTERN = /^\d{8}T\d{6}Z-[0-9a-f]{8}$/;

function normalizedArchitecture(value: string): "amd64" | "arm64" | undefined {
  const platform = ARCHITECTURE_PLATFORMS[value.toLowerCase()];
  if (platform === "linux/amd64") {
    return "amd64";
  }
  if (platform === "linux/arm64") {
    return "arm64";
  }
  return undefined;
}

function validateIntent(intent: LabIntent): void {
  if (intent.schema_version !== "anitrend.platform.lab-intent.v1" || intent.environment !== "lab") {
    throw new Error("Pulumi Docker lab accepts only a versioned lab environment intent");
  }
  if (!RUN_ID_PATTERN.test(intent.run_id)) {
    throw new Error("Pulumi Docker lab requires a unique timestamped run ID");
  }
  if (!intent.context_name || !intent.allowed_docker_contexts.includes(intent.context_name)) {
    throw new Error("Docker context is not explicitly allowlisted for the lab");
  }
  if (RESERVED_CONTEXT.test(intent.context_name)) {
    throw new Error("production and non-lab Docker contexts are refused");
  }
  if (!intent.docker_host.startsWith("unix://") && !intent.docker_host.startsWith("npipe://")) {
    throw new Error("Pulumi Docker lab requires an explicitly selected local Docker endpoint");
  }
  if (intent.host_os !== "Darwin" && intent.host_os !== "Linux") {
    throw new Error("Pulumi Docker lab supports only macOS and Linux hosts");
  }
  const hostArchitecture = normalizedArchitecture(intent.host_architecture);
  const dockerArchitecture = normalizedArchitecture(intent.docker_architecture);
  if (hostArchitecture === undefined || dockerArchitecture === undefined) {
    throw new Error("Pulumi Docker lab supports only amd64 and arm64 host architectures");
  }
  if (intent.image_platform !== "linux/amd64" && intent.image_platform !== "linux/arm64") {
    throw new Error("unsupported SSH fixture platform");
  }
  if (intent.image_platform !== ARCHITECTURE_PLATFORMS[intent.docker_architecture.toLowerCase()]) {
    throw new Error("SSH fixture platform does not match the selected Docker daemon architecture");
  }
  if (!imageLock.ssh_fixture.platforms.includes(intent.image_platform)) {
    throw new Error("SSH fixture image does not support the selected platform");
  }
  if (!Number.isSafeInteger(intent.revision) || intent.revision < 1) {
    throw new Error("lab revision must be a positive integer");
  }
  if (!Number.isSafeInteger(intent.ssh_host_port) || intent.ssh_host_port < 1024 || intent.ssh_host_port > 65535) {
    throw new Error("SSH host port must be between 1024 and 65535");
  }
  if (!/^ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\r\n]+)?$/.test(intent.public_key)) {
    throw new Error("the lab requires one generated SSH ed25519 public key");
  }
}

function labels(intent: LabIntent, resource: string): Array<{ label: string; value: string }> {
  return [
    { label: "anitrend.platform.managed-by", value: "pulumi" },
    { label: "anitrend.platform.environment", value: "lab" },
    { label: "anitrend.platform.run-id", value: intent.run_id },
    { label: "anitrend.platform.resource", value: resource },
    { label: "anitrend.platform.revision", value: String(intent.revision) },
  ];
}

export function createLabResources(intent: LabIntent): {
  outputs: pulumi.Output<LabOutputs>;
  container: docker.Container;
} {
  validateIntent(intent);

  const imageRef = imageLock.ssh_fixture.image;
  const imageDigest = imageRef.split("@")[1];
  if (imageDigest === undefined) {
    throw new Error("SSH fixture image lock must contain an immutable digest");
  }

  const baseName = `anitrend-platform-lab-${intent.run_id}`;
  const provider = new docker.Provider("platform-lab-docker", { host: intent.docker_host });
  const image = new docker.RemoteImage(
    "platform-lab-ssh-image",
    { name: imageRef, platform: intent.image_platform, keepLocally: true },
    { provider },
  );
  const network = new docker.Network(
    "platform-lab-network",
    {
      name: `${baseName}-network`,
      driver: "bridge",
      internal: false,
      labels: labels(intent, "network"),
    },
    { provider },
  );
  const volume = new docker.Volume(
    "platform-lab-config",
    {
      name: `${baseName}-config`,
      driver: "local",
      labels: labels(intent, "volume"),
    },
    { provider },
  );
  const container = new docker.Container(
    "platform-lab-ssh",
    {
      name: `${baseName}-ssh`,
      image: image.imageId,
      envs: [
        "PUID=1000",
        "PGID=1000",
        "TZ=Etc/UTC",
        "USER_NAME=ansible",
        `PUBLIC_KEY=${intent.public_key}`,
        "SUDO_ACCESS=false",
        "PASSWORD_ACCESS=false",
      ],
      ports: [{ internal: imageLock.ssh_fixture.port, external: intent.ssh_host_port, ip: "127.0.0.1", protocol: "tcp" }],
      networksAdvanced: [{ name: network.name }],
      volumes: [{ volumeName: volume.name, containerPath: "/config" }],
      labels: labels(intent, "ssh-fixture"),
      memory: 512,
      memorySwap: 1024,
      privileged: false,
      restart: "no",
      healthcheck: {
        tests: ["CMD", "busybox", "nc", "-z", "127.0.0.1", String(imageLock.ssh_fixture.port)],
        interval: "5s",
        timeout: "3s",
        retries: 12,
        startPeriod: "10s",
      },
      wait: true,
      mustRun: true,
    },
    { provider, dependsOn: [image, network, volume] },
  );

  const hostArchitecture = normalizedArchitecture(intent.host_architecture);
  const dockerArchitecture = normalizedArchitecture(intent.docker_architecture);
  if (hostArchitecture === undefined || dockerArchitecture === undefined) {
    throw new Error("validated lab architecture could not be normalized");
  }
  const executionMode = hostArchitecture === dockerArchitecture ? "native" : "emulated";
  const outputs = pulumi
    .all([network.name, volume.name, container.name, image.imageId])
    .apply(([networkName, volumeName, containerName, imageId]): LabOutputs => ({
      schema_version: "anitrend.platform.lab-output.v1",
      environment: "lab",
      run_id: intent.run_id,
      network_name: networkName,
      volume_name: volumeName,
      container_name: containerName,
      ssh_host_port: intent.ssh_host_port,
      image_ref: imageRef,
      image_id: imageId,
      image_digest: imageDigest,
      image_platform: intent.image_platform,
      host_os: intent.host_os,
      host_architecture: intent.host_architecture,
      docker_os: intent.docker_os,
      docker_architecture: intent.docker_architecture,
      execution_mode: executionMode,
    }));
  return { outputs, container };
}