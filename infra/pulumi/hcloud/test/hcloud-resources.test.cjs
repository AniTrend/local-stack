const assert = require("node:assert/strict");
const test = require("node:test");
const pulumi = require("@pulumi/pulumi");
const hcloud = require("@pulumi/hcloud");
const { validIntent } = require("./fixtures.cjs");
const { validatePulumiInventory } = require("../.artifacts/build/hcloud/inventory.js");

const resources = [];
const invocations = [];

const resourceOptions = [];
const hcloudLabelValue = /^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,61}[A-Za-z0-9])?$/;

pulumi.runtime.setMocks(
  {
    newResource(args) {
      resources.push(args);
      const state = { ...args.inputs };
      switch (args.type) {
        case "pulumi:pulumi:Stack":
          return { id: args.name, state };
        case "hcloud:index/network:Network":
          return { id: "11", state };
        case "hcloud:index/networkSubnet:NetworkSubnet":
          return { id: "12", state };
        case "hcloud:index/firewall:Firewall":
          return { id: "21", state };
        case "hcloud:index/server:Server":
          return { id: "31", state: { ...state, ipv4Address: "203.0.113.17", ipv6Address: "2001:db8::17" } };
        case "hcloud:index/serverNetwork:ServerNetwork":
          return { id: "32", state: { ...state, ip: "10.42.1.10" } };
        case "hcloud:index/volume:Volume":
          return { id: "41", state: { ...state, linuxDevice: "/dev/disk/by-id/scsi-0HC_Volume_41" } };
        case "hcloud:index/volumeAttachment:VolumeAttachment":
          return { id: "42", state };
        case "hcloud:index/zoneRrset:ZoneRrset":
          return { id: "51", state };
        case "pulumi:providers:hcloud":
          return { id: args.name, state };
        default:
          throw new Error(`Unexpected resource type ${args.type}`);
      }
    },
    call(args) {
      invocations.push(args);
      switch (args.token) {
        case "hcloud:index/getLocation:getLocation":
          return { id: 1, name: "nbg1", networkZone: "eu-central", city: "Nuremberg", country: "DE" };
        case "hcloud:index/getServerType:getServerType":
          return {
            id: 2,
            name: "cx23",
            architecture: "x86",
            locations: [{ id: 1, name: "nbg1", available: true, isDeprecated: false }],
          };
        case "hcloud:index/getImage:getImage":
          return {
            id: 3,
            name: "ubuntu-24.04",
            type: "system",
            architecture: "x86",
            isDeprecated: false,
          };
        case "hcloud:index/getSshKey:getSshKey":
          return { id: 4, name: "anitrend-ops", publicKey: "ssh-ed25519 AAAA test-only" };
        case "hcloud:index/getZone:getZone":
          return { id: 5, name: "example.invalid" };
        default:
          throw new Error(`Unexpected invoke ${args.token}`);
      }
    },
  },
  "anitrend-platform-hcloud",
  "production",
);

const { createHcloudInventory, protectedOptions, validateHcloudPreflight } = require("../.artifacts/build/hcloud/resources.js");
const provider = new hcloud.Provider("test-provider", { token: "mock-provider-value" });

test("provisions protected HCloud resources and exports schema-valid non-secret inventory", async () => {
  const intent = validIntent();
  intent.project_ref = "anitrend/production";
  const longDnsHostname = `${"a".repeat(40)}.${"b".repeat(40)}.example.invalid`;
  intent.private_routes = [
    {
      hostname: "postgres.internal.example.invalid",
      service_ref: "postgres",
      port: 5432,
      protocol: "tcp",
      source_cidrs: ["10.42.1.0/24"],
    },
  ];
  intent.dns_provider_ref = "hcloud";
  intent.dns_zone_ref = "example.invalid";
  intent.dns_records = [
    {
      hostname: "api.example.invalid",
      record_type: "A",
      target_ref: "server:public-ipv4",
      ttl_seconds: 300,
    },
    {
      hostname: "api.example.invalid",
      record_type: "AAAA",
      target_ref: "server:public-ipv6",
      ttl_seconds: 300,
    },
    {
      hostname: "www.example.invalid",
      record_type: "CNAME",
      target_ref: "api.example.invalid",
      ttl_seconds: 300,
    },
  ];

  intent.dns_records.push(
    {
      hostname: "example.invalid",
      record_type: "A",
      target_ref: "server:public-ipv4",
      ttl_seconds: 300,
    },
    {
      hostname: longDnsHostname,
      record_type: "A",
      target_ref: "server:public-ipv4",
      ttl_seconds: 300,
    },
    {
      hostname: "alias.example.invalid",
      record_type: "CNAME",
      target_ref: "api.example.invalid.",
      ttl_seconds: 300,
    },
  );

  const stack = await pulumi.runtime.runInPulumiStack(async () => {
    pulumi.runtime.registerStackTransformation(({ type, opts }) => {
      if (type.startsWith("hcloud:index/")) {
        resourceOptions.push({
          type,
          protect: opts.protect,
          replaceOnChanges: opts.replaceOnChanges,
        });
      }
      return undefined;
    });
    return { inventory: await createHcloudInventory(intent, provider).promise() };
  });
  const unvalidatedInventory = stack.inventory;
  const inventory = validatePulumiInventory(unvalidatedInventory);
  const resource = (type) => resources.find((item) => item.type === type);
  const firewall = resource("hcloud:index/firewall:Firewall");
  const network = resource("hcloud:index/network:Network");
  const subnet = resource("hcloud:index/networkSubnet:NetworkSubnet");
  const server = resource("hcloud:index/server:Server");
  const serverNetwork = resource("hcloud:index/serverNetwork:ServerNetwork");
  const volume = resource("hcloud:index/volume:Volume");
  const volumeAttachment = resource("hcloud:index/volumeAttachment:VolumeAttachment");
  const rrsets = resources.filter((item) => item.type === "hcloud:index/zoneRrset:ZoneRrset");

  assert.ok(firewall.inputs.rules.some((rule) => rule.port === "22" && rule.sourceIps[0] === "198.51.100.10/32"));
  assert.ok(firewall.inputs.rules.some((rule) => rule.port === "443" && rule.protocol === "tcp"));
  assert.ok(firewall.inputs.rules.some((rule) => rule.port === "5432" && rule.sourceIps[0] === "10.42.1.0/24"));
  assert.equal(network.inputs.ipRange, "10.42.0.0/16");
  assert.equal(network.inputs.deleteProtection, true);
  assert.equal(subnet.inputs.networkZone, "eu-central");
  assert.equal(server.inputs.serverType, "cx23");
  assert.equal(server.inputs.image, "ubuntu-24.04");
  assert.deepEqual(server.inputs.sshKeys, ["anitrend-ops"]);
  assert.deepEqual(server.inputs.firewallIds, [21]);
  assert.equal(server.inputs.deleteProtection, true);
  assert.equal(server.inputs.labels["anitrend.platform.environment"], "production");
  assert.equal(server.inputs.labels["anitrend.platform.managed-by"], "pulumi");
  assert.equal(server.inputs.labels["anitrend.platform.project-ref"], "anitrend-production");
  assert.equal(server.inputs.labels["anitrend.platform.resource"], "server");
  assert.equal(server.inputs.rebuildProtection, true);
  assert.equal(server.inputs.userData, undefined);
  assert.equal(serverNetwork.inputs.serverId, 31);
  assert.equal(serverNetwork.inputs.subnetId, "12");
  assert.equal(volume.inputs.format, "ext4");
  assert.equal(volume.inputs.deleteProtection, true);
  assert.equal(volumeAttachment.inputs.serverId, 31);
  assert.equal(volumeAttachment.inputs.volumeId, 41);
  assert.equal(rrsets.length, 6);
  assert.ok(rrsets.some((item) => item.inputs.type === "A" && item.inputs.records[0].value === "203.0.113.17"));
  assert.equal(
    rrsets.find((item) => item.inputs.name === "www").inputs.records[0].value,
    "api.example.invalid.",
  );
  assert.equal(
    rrsets.find((item) => item.inputs.name === "alias").inputs.records[0].value,
    "api.example.invalid.",
  );
  for (const item of resources.filter((resource) => resource.inputs.labels !== undefined)) {
    for (const value of Object.values(item.inputs.labels)) {
      assert.ok(value.length <= 63);
      assert.match(value, hcloudLabelValue);
    }
  }
  assert.ok(rrsets.some((item) => item.inputs.type === "AAAA" && item.inputs.records[0].value === "2001:db8::17"));
  assert.ok(invocations.some((item) => item.token === "hcloud:index/getSshKey:getSshKey"));
  assert.ok(invocations.some((item) => item.token === "hcloud:index/getZone:getZone"));

  assert.equal(inventory.environment, "production");
  assert.equal(inventory.readiness, "ready");
  assert.equal(inventory.hosts[0].public_ipv4, "203.0.113.17");
  assert.equal(inventory.hosts[0].private_addresses[0], "10.42.1.10");
  assert.equal(inventory.hosts[0].expected_host_identity_ref, "ssh-host-ca:anitrend-production");
  assert.equal(inventory.hosts[0].bootstrap_user, "ansible");
  assert.equal(inventory.volumes[0].filesystem, "ext4");
  assert.deepEqual(inventory.firewall_policy.ssh_source_cidrs, ["198.51.100.10/32"]);
  assert.equal(inventory.firewall_policy.public_routes[0].port, 443);
  assert.equal(inventory.firewall_policy.private_routes[0].port, 5432);
  assert.equal(inventory.volumes[0].mount_path, "/var/lib/postgresql");
  assert.ok(inventory.resource_ids.some((item) => item.kind === "server_network"));
  assert.ok(!JSON.stringify(inventory).includes("mock-provider-value"));
  assert.ok(!JSON.stringify(inventory).includes("ssh-ed25519"));
  const productionOptions = resourceOptions.filter((options) => options.type !== "pulumi:providers:hcloud");
  assert.ok(productionOptions.length > 0);
  assert.ok(productionOptions.every((options) => options.protect === true));
  const serverOptions = productionOptions.find((options) => options.type === "hcloud:index/server:Server");
  assert.ok(serverOptions);
  assert.deepEqual(serverOptions.replaceOnChanges, ["serverType", "image"]);
});

test("production resources are protected while rehearsal deletion remains available", () => {
  const production = validIntent();
  assert.equal(protectedOptions(production, provider).protect, true);

  const rehearsal = validIntent();
  rehearsal.environment = "rehearsal";
  rehearsal.ttl_hours = 24;
  rehearsal.safety_policy.allow_destroy = true;
  rehearsal.safety_policy.protect_resources = false;
  assert.equal(protectedOptions(rehearsal, provider).protect, false);
  assert.equal(protectedOptions(rehearsal, provider, true).protect, true);
});

test("rejects a server type architecture mismatch during HCloud preflight", () => {
  const intent = validIntent();
  intent.architecture = "arm64";

  assert.throws(
    () =>
      validateHcloudPreflight(
        intent,
        { name: "nbg1", networkZone: "eu-central" },
        { name: "cx23", architecture: "x86", locations: [] },
        { name: "ubuntu-24.04", type: "system", architecture: "x86", isDeprecated: false },
        [{ id: 4, name: "anitrend-ops" }],
        undefined,
      ),
    /does not match requested architecture arm64/i,
  );
});
