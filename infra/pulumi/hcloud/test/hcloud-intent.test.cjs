const assert = require("node:assert/strict");
const test = require("node:test");
const { parseEnvironmentIntent } = require("../.artifacts/build/hcloud/intent.js");
const { validIntent } = require("./fixtures.cjs");
function parseIntent(intent) {
  return parseEnvironmentIntent(intent, intent.project_ref);
}


test("accepts confirmed production intent with an approved cost estimate", () => {
  const intent = validIntent();

  assert.deepEqual(parseIntent(intent), intent);
});

test("rejects project identities that cannot be used as safe HCloud references", () => {
  const intent = validIntent();
  intent.project_ref = "production project";

  assert.throws(() => parseIntent(intent), /project_ref.*pattern/i);
});

test("rejects a mismatch between configured and intent project identity", () => {
  assert.throws(() => parseEnvironmentIntent(validIntent(), "other-project"), /project reference/i);
});

test("rejects a monthly estimate above the approved budget ceiling", () => {
  const intent = validIntent();
  intent.estimated_monthly_cost_eur = 501;

  assert.throws(() => parseIntent(intent), /estimated monthly cost exceeds budget limit/i);
});

test("rejects a non-Pulumi-Cloud state backend reference", () => {
  const intent = validIntent();
  intent.state_backend_ref = "file:///tmp/platform-state";

  assert.throws(() => parseIntent(intent), /state_backend_ref.*pattern/i);
});

test("rejects raw SSH key material, noncanonical CIDRs, and unsafe mount paths", () => {
  const rawKey = validIntent();
  rawKey.ssh_key_refs = ["ssh-ed25519 AAAA test-only"];
  assert.throws(() => parseIntent(rawKey), /ssh_key_refs.*pattern/i);

  const hostCidr = validIntent();
  hostCidr.network_cidrs[0].cidr = "10.42.0.1/16";
  assert.throws(() => parseIntent(hostCidr), /network address/i);

  const unsafeMount = validIntent();
  unsafeMount.volumes[0].mount_path = "/var/lib/../postgres";
  assert.throws(() => parseIntent(unsafeMount), /mount_path/i);
});

test("rejects system-critical and nested host mount paths", () => {
  const systemMount = validIntent();
  systemMount.volumes[0].mount_path = "/etc";
  assert.throws(() => parseIntent(systemMount), /mount_path/i);

  const nestedMount = validIntent();
  nestedMount.volumes.push({
    ...nestedMount.volumes[0],
    id_ref: "second-volume",
    mount_path: nestedMount.volumes[0].mount_path + "/nested",
  });
  assert.throws(() => parseIntent(nestedMount), /overlapping.*mount path/i);
});

test("rejects public SSH and non-web application ingress", () => {
  const publicSsh = validIntent();
  publicSsh.public_routes[0].port = 22;
  publicSsh.public_routes[0].protocol = "tcp";
  assert.throws(() => parseIntent(publicSsh), /public route/i);

  const openAdmin = validIntent();
  openAdmin.ssh_source_cidrs = ["0.0.0.0/0"];
  assert.throws(() => parseIntent(openAdmin), /ssh_source_cidrs.*global/i);
});

test("rejects firewall CIDRs with host bits", () => {
  const sshHostBits = validIntent();
  sshHostBits.ssh_source_cidrs = ["198.51.100.10/24"];
  assert.throws(() => parseIntent(sshHostBits), /network address/i);

  const privateRouteHostBits = validIntent();
  privateRouteHostBits.private_routes = [
    {
      hostname: "postgres.internal.example.invalid",
      service_ref: "postgres",
      port: 5432,
      protocol: "tcp",
      source_cidrs: ["10.42.1.1/24"],
    },
  ];
  assert.throws(() => parseIntent(privateRouteHostBits), /network address/i);

  const ipv6HostBits = validIntent();
  ipv6HostBits.ssh_source_cidrs = ["2001:db8::1/64"];
  assert.throws(() => parseIntent(ipv6HostBits), /network address/i);
});

test("rejects globally reachable private routes", () => {
  const intent = validIntent();
  intent.private_routes.push({
    hostname: "postgres.internal.example.invalid",
    service_ref: "postgres",
    port: 5432,
    protocol: "tcp",
    source_cidrs: ["::/0"],
  });

  assert.throws(() => parseIntent(intent), /private_routes.*global/i);
});

test("rejects overlapping networks and subnets outside their parent range", () => {
  const overlapping = validIntent();
  overlapping.network_cidrs.push({
    name: "second",
    cidr: "10.42.1.0/24",
    subnet_cidr: "10.42.1.0/25",
    purpose: "database",
  });
  assert.throws(() => parseIntent(overlapping), /network cidr.*overlap/i);

  const outsideParent = validIntent();
  outsideParent.network_cidrs[0].subnet_cidr = "10.43.1.0/24";
  assert.throws(() => parseIntent(outsideParent), /subnet.*contained/i);
});

test("rejects production destruction policy and rehearsal without a TTL", () => {
  const productionDestroyable = validIntent();
  productionDestroyable.safety_policy.allow_destroy = true;
  assert.throws(() => parseIntent(productionDestroyable), /schema|production/i);

  const rehearsalWithoutTtl = validIntent();
  rehearsalWithoutTtl.environment = "rehearsal";
  rehearsalWithoutTtl.safety_policy.allow_destroy = true;
  assert.throws(() => parseIntent(rehearsalWithoutTtl), /schema|ttl/i);
});

test("rejects volume sizes outside Hetzner limits and aggregate capacity", () => {
  const tooSmall = validIntent();
  tooSmall.volumes[0].size_gb = 9;
  assert.throws(() => parseIntent(tooSmall), /size_gb/i);

  const tooLarge = validIntent();
  tooLarge.volumes[0].size_gb = 10001;
  assert.throws(() => parseIntent(tooLarge), /size_gb/i);

  const overCapacity = validIntent();
  const original = overCapacity.volumes[0];
  overCapacity.volumes = [
    { ...original, id_ref: "first", size_gb: 6000, mount_path: "/mnt/first" },
    { ...original, id_ref: "second", size_gb: 5000, mount_path: "/mnt/second" },
  ];
  assert.throws(() => parseIntent(overCapacity), /total volume capacity/i);
});
