import * as pulumi from "@pulumi/pulumi";
import type { LabIntent } from "../shared/lab-contracts";
import { createLabResources } from "./lab";

const config = new pulumi.Config("lab");
const allowedDockerContexts = config.requireObject<unknown>("allowedDockerContexts");
if (
  !Array.isArray(allowedDockerContexts) ||
  !allowedDockerContexts.every((context): context is string => typeof context === "string")
) {
  throw new Error("lab:allowedDockerContexts must be a JSON array of context names");
}

const imagePlatform = config.require("imagePlatform");
if (imagePlatform !== "linux/amd64" && imagePlatform !== "linux/arm64") {
  throw new Error("lab:imagePlatform must be linux/amd64 or linux/arm64");
}

const hostOs = config.require("hostOs");
if (hostOs !== "Darwin" && hostOs !== "Linux") {
  throw new Error("lab:hostOs must be Darwin or Linux");
}
const sshHostPort = config.requireNumber("sshHostPort");
if (!Number.isSafeInteger(sshHostPort) || sshHostPort < 1024 || sshHostPort > 65535) {
  throw new Error("lab:sshHostPort must be between 1024 and 65535");
}

const intent: LabIntent = {
  schema_version: "anitrend.platform.lab-intent.v1",
  environment: "lab",
  run_id: config.require("runId"),
  context_name: config.require("dockerContext"),
  allowed_docker_contexts: allowedDockerContexts,
  docker_host: config.require("dockerHost"),
  host_os: hostOs,
  host_architecture: config.require("hostArchitecture"),
  docker_os: config.require("dockerOs"),
  docker_architecture: config.require("dockerArchitecture"),
  image_platform: imagePlatform,
  ssh_host_port: sshHostPort,
  revision: config.requireNumber("revision"),
  public_key: config.require("publicKey"),
};

const lab = createLabResources(intent);
export const labOutputs = lab.outputs;
