import * as pulumi from "@pulumi/pulumi";
import * as hcloud from "@pulumi/hcloud";
import { parseEnvironmentIntent } from "./intent";
import { validatePulumiInventory } from "./inventory";
import { createHcloudInventory } from "./resources";

const stackName = pulumi.getStack();
const config = new pulumi.Config();
const hcloudConfig = new pulumi.Config("hcloud");
const platformConfig = new pulumi.Config("platform");
const configuredProjectRef = platformConfig.require("hcloud-project-ref");
const intent = parseEnvironmentIntent(config.requireObject<unknown>("environment-intent"), configuredProjectRef);

if (stackName !== intent.environment) {
  throw new Error(`HCloud stack ${stackName} must match intent environment ${intent.environment}`);
}

const provider = new hcloud.Provider("hcloud", {
  token: hcloudConfig.requireSecret("token"),
});

export const inventory = createHcloudInventory(intent, provider).apply(validatePulumiInventory);
