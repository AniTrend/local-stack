export type LabImagePlatform = "linux/amd64" | "linux/arm64";

export interface LabIntent {
  schema_version: "anitrend.platform.lab-intent.v1";
  environment: "lab";
  run_id: string;
  context_name: string;
  allowed_docker_contexts: string[];
  docker_host: string;
  host_os: "Darwin" | "Linux";
  host_architecture: string;
  docker_os: string;
  docker_architecture: string;
  ssh_host_port: number;
  image_platform: LabImagePlatform;
  revision: number;
  public_key: string;
}

export interface LabOutputs {
  schema_version: "anitrend.platform.lab-output.v1";
  environment: "lab";
  run_id: string;
  network_name: string;
  volume_name: string;
  container_name: string;
  ssh_host_port: number;
  image_ref: string;
  image_digest: string;
  image_id: string;
  image_platform: LabImagePlatform;
  host_os: "Darwin" | "Linux";
  host_architecture: string;
  docker_os: string;
  docker_architecture: string;
  execution_mode: "native" | "emulated";
}
