const assert = require("node:assert/strict");
const { test } = require("node:test");
const pulumi = require("@pulumi/pulumi");

const MOCK_IMAGE_ID = "sha256:1111111111111111111111111111111111111111111111111111111111111111";
const registrations = [];
const containerReady = Promise.withResolvers();
pulumi.runtime.setMocks(
  {
    newResource(args) {
      registrations.push(args);
      if (Array.isArray(args.inputs?.ports)) {
        containerReady.resolve(args);
      }
      const state = { ...args.inputs };
      if (args.type === "docker:index/remoteImage:RemoteImage") {
        state.imageId = MOCK_IMAGE_ID;
      }
      if (Array.isArray(state.ports)) {
        state.ports = state.ports.map((port) => ({ ...port, external: 32000 }));
      }
      return { id: `${args.name}_id`, state };
    },
    call(args) {
      return args.inputs;
    },
  },
  "anitrend-platform-lab",
  "test",
  false,
);

const { createLabResources } = require("../.artifacts/build/docker/lab.js");

const validIntent = {
  schema_version: "anitrend.platform.lab-intent.v1",
  environment: "lab",
  run_id: "20261025T000000Z-a1b2c3d4",
  context_name: "fixture-local",
  allowed_docker_contexts: ["fixture-local"],
  docker_host: "unix:///var/run/docker.sock",
  host_os: "Linux",
  host_architecture: "x86_64",
  docker_os: "Ubuntu 24.04 LTS",
  docker_architecture: "x86_64",
  image_platform: "linux/amd64",
  ssh_host_port: 32123,
  revision: 1,
  public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIABBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB platform-lab",
};

test("creates isolated SSH resources labelled and bound to loopback for one run", async () => {
  const lab = createLabResources(validIntent);
  const outputsReady = Promise.withResolvers();
  lab.outputs.apply(outputsReady.resolve);
  const [container, outputs] = await Promise.all([containerReady.promise, outputsReady.promise]);
  const resources = registrations.filter((resource) => resource.type.startsWith("docker:index/"));
  const runIdLabel = "anitrend.platform.run-id";

  assert.equal(resources.length, 4);
  const network = resources.find((resource) => resource.type === "docker:index/network:Network");
  assert.ok(network);
  assert.equal(network.inputs.internal, false);
  for (const resource of resources.filter((item) => item.inputs.labels)) {
    assert.ok(resource.inputs.labels.some((label) => label.label === runIdLabel && label.value === validIntent.run_id));
  }
  assert.equal(container.inputs.name, `anitrend-platform-lab-${validIntent.run_id}-ssh`);
  assert.equal(container.inputs.ports.length, 1);
  assert.equal(container.inputs.ports[0].ip, "127.0.0.1");
  assert.equal(container.inputs.ports[0].internal, 2222);
  assert.equal(container.inputs.ports[0].external, validIntent.ssh_host_port);
  assert.equal(container.inputs.memory, 512);
  assert.equal(container.inputs.memorySwap, 1024);
  assert.equal(container.inputs.privileged, false);
  assert.equal(container.inputs.wait, true);
  assert.deepEqual(container.inputs.healthcheck.tests, ["CMD", "busybox", "nc", "-z", "127.0.0.1", "2222"]);
  assert.equal(container.inputs.volumes[0].containerPath, "/config");
  assert.equal(container.inputs.networksAdvanced.length, 1);
  assert.equal(outputs.ssh_host_port, validIntent.ssh_host_port);
  assert.equal(outputs.image_id, MOCK_IMAGE_ID);
  assert.equal(outputs.image_digest, "sha256:0f535b0faa7448511b23528165e9fbd4f1fe563b861b3dcaa5ddb0ddbfe2254c");
});

test("rejects non-lab or unallowlisted Docker intents before registering resources", () => {
  const before = registrations.length;

  assert.throws(() => createLabResources({ ...validIntent, environment: "production" }), /lab environment/i);
  assert.throws(() => createLabResources({ ...validIntent, context_name: "production", allowed_docker_contexts: ["production"] }), /production/i);
  assert.throws(() => createLabResources({ ...validIntent, docker_host: "ssh://remote.invalid" }), /local Docker endpoint/i);
  assert.throws(() => createLabResources({ ...validIntent, image_platform: "linux/ppc64le" }), /unsupported.*platform/i);
  assert.throws(() => createLabResources({ ...validIntent, ssh_host_port: 0 }), /SSH host port/i);
  assert.equal(registrations.length, before);
});
