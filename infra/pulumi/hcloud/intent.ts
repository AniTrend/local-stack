import { isIP } from "node:net";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020";
import type { EnvironmentIntent, RouteIntent } from "../shared/contracts";
import environmentIntentSchema from "../shared/environment-intent.schema.json";

const ajv = new Ajv2020({ allErrors: true, strict: true });
const validateSchema = ajv.compile<EnvironmentIntent>(environmentIntentSchema);

interface Ipv4Range {
  start: bigint;
  end: bigint;
}

function parseIpv4Cidr(value: string, field: string): Ipv4Range {
  const parts = value.split("/");
  if (parts.length !== 2 || isIP(parts[0]) !== 4 || !/^(0|[1-9][0-9]*)$/.test(parts[1])) {
    throw new Error(`${field} must be a canonical IPv4 CIDR`);
  }

  const prefix = Number(parts[1]);
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > 32) {
    throw new Error(`${field} has an invalid IPv4 prefix`);
  }

  let address = 0n;
  for (const octet of parts[0].split(".")) {
    address = (address << 8n) | BigInt(Number(octet));
  }

  const hostBits = BigInt(32 - prefix);
  const hostMask = (1n << hostBits) - 1n;
  const start = address & ~hostMask;
  if (start !== address) {
    throw new Error(`${field} must use its network address, not a host address`);
  }

  return { start, end: start | hostMask };
}

function isRfc1918(range: Ipv4Range): boolean {
  const privateRanges = [
    { start: 0x0a000000n, end: 0x0affffffn },
    { start: 0xac100000n, end: 0xac1fffffn },
    { start: 0xc0a80000n, end: 0xc0a8ffffn },
  ];
  return privateRanges.some((candidate) => range.start >= candidate.start && range.end <= candidate.end);
}

function rangesOverlap(left: Ipv4Range, right: Ipv4Range): boolean {
  return left.start <= right.end && right.start <= left.end;
}

function isContained(child: Ipv4Range, parent: Ipv4Range): boolean {
  return child.start >= parent.start && child.end <= parent.end;
}

function ipv6AddressValue(value: string, field: string): bigint {
  let address = value.toLowerCase();
  if (address.includes(".")) {
    const separator = address.lastIndexOf(":");
    const octets = address.slice(separator + 1).split(".").map(Number);
    if (separator < 0 || octets.length !== 4 || octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) {
      throw new Error(`${field} must be a valid IPv6 CIDR`);
    }
    address = `${address.slice(0, separator + 1)}${(octets[0] * 256 + octets[1]).toString(16)}:${(octets[2] * 256 + octets[3]).toString(16)}`;
  }

  const compression = address.indexOf("::");
  let groups: string[];
  if (compression < 0) {
    groups = address.split(":");
  } else {
    const left = address.slice(0, compression).split(":").filter(Boolean);
    const right = address.slice(compression + 2).split(":").filter(Boolean);
    const zeroGroups = 8 - left.length - right.length;
    if (zeroGroups < 1) {
      throw new Error(`${field} must be a valid IPv6 CIDR`);
    }
    groups = [...left, ...Array<string>(zeroGroups).fill("0"), ...right];
  }
  if (groups.length !== 8 || groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) {
    throw new Error(`${field} must be a valid IPv6 CIDR`);
  }
  return groups.reduce((result, group) => (result << 16n) | BigInt(Number.parseInt(group, 16)), 0n);
}

function validateFirewallCidr(value: string, field: string, allowDefaultRoute: boolean): void {
  const parts = value.split("/");
  if (parts.length !== 2 || parts[0].includes("%") || !/^(0|[1-9][0-9]*)$/.test(parts[1])) {
    throw new Error(`${field} must be an IP CIDR`);
  }

  const family = isIP(parts[0]);
  const prefix = Number(parts[1]);
  const maxPrefix = family === 4 ? 32 : family === 6 ? 128 : -1;
  if (maxPrefix < 0 || !Number.isInteger(prefix) || prefix < 0 || prefix > maxPrefix) {
    throw new Error(`${field} has an invalid IP CIDR prefix`);
  }
  if (family === 4) {
    parseIpv4Cidr(value, field);
  } else {
    const hostBits = BigInt(128 - prefix);
    const hostMask = (1n << hostBits) - 1n;
    if ((ipv6AddressValue(parts[0], field) & hostMask) !== 0n) {
      throw new Error(`${field} must use its network address, not a host address`);
    }
  }
  if (!allowDefaultRoute && prefix === 0) {
    throw new Error(`${field} must not allow a global source`);
  }
}

function validateDomainName(value: string, field: string): void {
  const normalized = value.endsWith(".") ? value.slice(0, -1) : value;
  const labels = normalized.split(".");
  if (
    normalized.length > 253 ||
    labels.length < 2 ||
    labels.some((label) => label.length > 63 || !/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/i.test(label))
  ) {
    throw new Error(`${field} must be a valid fully qualified DNS name`);
  }
}

function validateRoute(route: RouteIntent, kind: "public" | "private", index: number): void {
  const field = `${kind}_routes[${index}]`;
  validateDomainName(route.hostname, `${field}.hostname`);
  if (route.source_cidrs.length === 0) {
    throw new Error(`${field} must have at least one source CIDR`);
  }
  for (const source of route.source_cidrs) {
    validateFirewallCidr(source, `${field}.source_cidrs`, kind === "public");
  }

  if (kind === "public") {
    if (!([80, 443] as const).includes(route.port as 80 | 443) || route.protocol === "udp") {
      throw new Error("public routes are limited to TCP ports 80 and 443");
    }
    if ((route.protocol === "http" && route.port !== 80) || (route.protocol === "https" && route.port !== 443)) {
      throw new Error(`${field} protocol and port do not match`);
    }
  }
}

function validateDnsTarget(recordType: string, target: string, index: number): void {
  const field = `dns_records[${index}].target_ref`;
  if (recordType === "A") {
    if (target !== "server:public-ipv4" && isIP(target) !== 4) {
      throw new Error(`${field} must reference server:public-ipv4 or an IPv4 address`);
    }
    return;
  }
  if (recordType === "AAAA") {
    if (target !== "server:public-ipv6" && isIP(target) !== 6) {
      throw new Error(`${field} must reference server:public-ipv6 or an IPv6 address`);
    }
    return;
  }
  if (target.startsWith("server:")) {
    throw new Error(`${field} cannot use an IP address for a CNAME`);
  }
  validateDomainName(target, field);
}

export function parseEnvironmentIntent(value: unknown, configuredProjectRef: string): EnvironmentIntent {
  if (!validateSchema(value)) {
    const details = validateSchema.errors
      ?.map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
      .join("; ");
    throw new Error(`HCloud environment intent failed schema validation${details ? `: ${details}` : ""}`);
  }

  const intent = value;
  if (!Number.isFinite(intent.budget_limit_eur) || !Number.isFinite(intent.estimated_monthly_cost_eur)) {
    throw new Error("budget and estimated monthly cost must be finite amounts");
  }
  if (intent.estimated_monthly_cost_eur > intent.budget_limit_eur) {
    throw new Error("estimated monthly cost exceeds budget limit");
  }
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(intent.project_ref)) {
    throw new Error("project_ref must be a bounded, non-secret project identity reference");
  }
  if (intent.project_ref !== configuredProjectRef) {
    throw new Error("HCloud provider project reference does not match the environment intent");
  }
  if (!intent.state_backend_ref.startsWith("pulumi-cloud:")) {
    throw new Error("HCloud state_backend_ref must identify Pulumi Cloud per the platform ADR");
  }

  const networkNames = new Set<string>();
  const networkRanges: Ipv4Range[] = [];
  const subnetRanges: Ipv4Range[] = [];
  for (const [index, network] of intent.network_cidrs.entries()) {
    if (networkNames.has(network.name)) {
      throw new Error(`network_cidrs contains duplicate name ${network.name}`);
    }
    networkNames.add(network.name);

    const networkRange = parseIpv4Cidr(network.cidr, `network_cidrs[${index}].cidr`);
    if (!isRfc1918(networkRange)) {
      throw new Error(`network_cidrs[${index}].cidr must be wholly within RFC1918 space`);
    }
    if (networkRanges.some((existing) => rangesOverlap(networkRange, existing))) {
      throw new Error(`network CIDR ranges overlap at ${network.name}`);
    }
    networkRanges.push(networkRange);

    const subnetRange = parseIpv4Cidr(network.subnet_cidr, `network_cidrs[${index}].subnet_cidr`);
    if (!isContained(subnetRange, networkRange)) {
      throw new Error(`subnet for ${network.name} must be contained in its parent network CIDR`);
    }
    if (subnetRanges.some((existing) => rangesOverlap(subnetRange, existing))) {
      throw new Error(`network subnet CIDR ranges overlap at ${network.name}`);
    }
    subnetRanges.push(subnetRange);
  }

  const volumeRefs = new Set<string>();
  const mountPaths = new Set<string>();
  for (const [index, volume] of intent.volumes.entries()) {
    if (!/^[a-z0-9][a-z0-9-]{0,31}$/.test(volume.id_ref)) {
      throw new Error(`volumes[${index}].id_ref must be a lowercase resource label`);
    }
    if (volumeRefs.has(volume.id_ref)) {
      throw new Error(`volumes contains duplicate reference ${volume.id_ref}`);
    }
    volumeRefs.add(volume.id_ref);
    if (!Number.isInteger(volume.size_gb) || volume.size_gb < 10 || volume.size_gb > 10000) {
      throw new Error(`volumes[${index}].size_gb must be between 10 and 10000 GB`);
    }
    if (
      !path.posix.isAbsolute(volume.mount_path) ||
      volume.mount_path === "/" ||
      path.posix.normalize(volume.mount_path) !== volume.mount_path ||
      volume.mount_path.split("/").some((segment) => segment === "." || segment === "..")
    ) {
      throw new Error(`volumes[${index}].mount_path must be a normalized absolute mount path`);
    }
    if (mountPaths.has(volume.mount_path)) {
      throw new Error(`volumes contains duplicate mount path ${volume.mount_path}`);
    }
    mountPaths.add(volume.mount_path);
  }
  const totalVolumeSizeGb = intent.volumes.reduce((total, volume) => total + volume.size_gb, 0);
  if (totalVolumeSizeGb > 10000) {
    throw new Error("total volume capacity cannot exceed 10000 GB per server");
  }

  for (const [index, reference] of intent.ssh_key_refs.entries()) {
    if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(reference)) {
      throw new Error(`ssh_key_refs[${index}] must be an SSH key name or numeric ID reference`);
    }
  }
  if (intent.ssh_source_cidrs.length === 0) {
    throw new Error("ssh_source_cidrs must contain at least one non-global source CIDR");
  }
  for (const source of intent.ssh_source_cidrs) {
    validateFirewallCidr(source, "ssh_source_cidrs", false);
  }
  intent.public_routes.forEach((route, index) => validateRoute(route, "public", index));
  intent.private_routes.forEach((route, index) => validateRoute(route, "private", index));

  if (intent.dns_provider_ref === "hcloud") {
    for (const [index, record] of intent.dns_records.entries()) {
      validateDomainName(record.hostname, `dns_records[${index}].hostname`);
      validateDnsTarget(record.record_type, record.target_ref, index);
    }
  }

  return intent;
}
