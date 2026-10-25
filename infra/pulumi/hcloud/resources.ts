import * as pulumi from "@pulumi/pulumi";
import * as hcloud from "@pulumi/hcloud";
import type { FirewallRule } from "@pulumi/hcloud/types/input";
import type { GetImageResult, GetLocationResult, GetServerTypeResult, GetSshKeyResult, GetZoneResult } from "@pulumi/hcloud";
import type {
  EnvironmentIntent,
  PulumiHostInventory,
  PulumiInventory,
  PulumiResourceIdentity,
  PulumiVolumeInventory,
} from "../shared/contracts";

export function protectedOptions(intent: EnvironmentIntent, provider: pulumi.ProviderResource, protect = intent.safety_policy.protect_resources): pulumi.CustomResourceOptions {
  return { provider, protect };
}

function resourceLabels(intent: EnvironmentIntent, resource: string): Record<string, string> {
  return {
    "anitrend.platform.environment": intent.environment,
    "anitrend.platform.managed-by": "pulumi",
    "anitrend.platform.project-ref": intent.project_ref,
    "anitrend.platform.resource": resource,
  };
}


function dnsRecordName(hostname: string, zoneName: string): string {
  const record = hostname.toLowerCase().replace(/\.$/, "");
  const zone = zoneName.toLowerCase().replace(/\.$/, "");
  if (record === zone) {
    return "@";
  }
  if (!record.endsWith(`.${zone}`)) {
    throw new Error(`DNS record hostname ${hostname} is outside the configured HCloud zone`);
  }
  return record.slice(0, -(zone.length + 1));
}

interface DnsRecordGroup {
  name: string;
  type: "A" | "AAAA" | "CNAME";
  ttl: number;
  targets: string[];
}

function groupDnsRecords(intent: EnvironmentIntent, zoneName: string): DnsRecordGroup[] {
  const groups = new Map<string, DnsRecordGroup>();
  const typesByName = new Map<string, Set<string>>();
  for (const record of intent.dns_records) {
    const name = dnsRecordName(record.hostname, zoneName);
    if (record.record_type === "CNAME" && name === "@") {
      throw new Error("HCloud DNS CNAME records are not allowed at the zone apex");
    }

    const types = typesByName.get(name) ?? new Set<string>();
    if (record.record_type === "CNAME" && types.size > 0) {
      throw new Error(`DNS CNAME ${record.hostname} conflicts with another record type`);
    }
    if (types.has("CNAME")) {
      throw new Error(`DNS record ${record.hostname} conflicts with an existing CNAME`);
    }
    types.add(record.record_type);
    typesByName.set(name, types);

    const key = `${name}\u0000${record.record_type}`;
    const group = groups.get(key);
    if (group === undefined) {
      groups.set(key, { name, type: record.record_type, ttl: record.ttl_seconds, targets: [record.target_ref] });
      continue;
    }
    if (group.ttl !== record.ttl_seconds) {
      throw new Error(`DNS RRset ${record.hostname} has conflicting TTL values`);
    }
    if (group.targets.includes(record.target_ref)) {
      throw new Error(`DNS RRset ${record.hostname} contains a duplicate target`);
    }
    group.targets.push(record.target_ref);
  }
  return [...groups.values()];
}

interface ValidatedHcloudPreflight {
  networkZone: string;
  dnsZoneId: string | undefined;
  dnsGroups: DnsRecordGroup[];
}

export function validateHcloudPreflight(
  intent: EnvironmentIntent,
  location: GetLocationResult,
  serverType: GetServerTypeResult,
  image: GetImageResult,
  sshKeys: GetSshKeyResult[],
  zone: GetZoneResult | undefined,
): ValidatedHcloudPreflight {
  const expectedArchitecture = intent.architecture === "amd64" ? "x86" : "arm";
  if (location.name !== intent.region || location.networkZone.length === 0) {
    throw new Error(`HCloud location ${intent.region} did not report a usable network zone`);
  }
  if (serverType.name !== intent.server_type || serverType.architecture !== expectedArchitecture) {
    throw new Error(`HCloud server type ${intent.server_type} does not match requested architecture ${intent.architecture}`);
  }
  const availableLocation = serverType.locations.find((candidate) => candidate.name === intent.region);
  if (availableLocation === undefined || !availableLocation.available || availableLocation.isDeprecated) {
    throw new Error(`HCloud server type ${intent.server_type} is unavailable or deprecated in ${intent.region}`);
  }
  if (
    image.name !== intent.os_image ||
    image.type !== "system" ||
    image.architecture !== expectedArchitecture ||
    image.isDeprecated
  ) {
    throw new Error(`HCloud OS image ${intent.os_image} is unavailable, deprecated, or incompatible`);
  }
  for (const [index, key] of sshKeys.entries()) {
    const requested = intent.ssh_key_refs[index];
    const numericId = /^[1-9][0-9]*$/.test(requested) ? Number(requested) : undefined;
    if (numericId !== undefined && Number.isSafeInteger(numericId) && key.id !== numericId) {
      throw new Error(`SSH key reference at index ${index} did not resolve to the requested HCloud key`);
    }
    if ((numericId === undefined || !Number.isSafeInteger(numericId)) && key.name !== requested) {
      throw new Error(`SSH key reference at index ${index} did not resolve to the requested HCloud key`);
    }
  }

  let dnsZoneId: string | undefined;
  let dnsGroups: DnsRecordGroup[] = [];
  if (intent.dns_provider_ref === "hcloud" && intent.dns_records.length > 0) {
    if (zone === undefined || zone.id === undefined || zone.name === undefined) {
      throw new Error("HCloud DNS zone lookup returned no stable zone identity");
    }
    dnsZoneId = String(zone.id);
    dnsGroups = groupDnsRecords(intent, zone.name);
  }
  return { networkZone: location.networkZone, dnsZoneId, dnsGroups };
}

function firewallRules(intent: EnvironmentIntent): FirewallRule[] {
  const rules: FirewallRule[] = [
    {
      direction: "in",
      protocol: "tcp",
      port: "22",
      sourceIps: intent.ssh_source_cidrs,
      description: "Restricted SSH administration",
    },
  ];
  for (const route of intent.public_routes) {
    rules.push({
      direction: "in",
      protocol: "tcp",
      port: String(route.port),
      sourceIps: route.source_cidrs,
      description: `Public ${route.protocol} ${route.hostname}`,
    });
  }
  for (const route of intent.private_routes) {
    rules.push({
      direction: "in",
      protocol: route.protocol === "udp" ? "udp" : "tcp",
      port: String(route.port),
      sourceIps: route.source_cidrs,
      description: `Private ${route.protocol} ${route.hostname}`,
    });
  }
  return rules;
}

function dnsTarget(record: DnsRecordGroup, target: string, server: hcloud.Server): pulumi.Input<string> {
  if (target === "server:public-ipv4" && record.type === "A") {
    return server.ipv4Address;
  }
  if (target === "server:public-ipv6" && record.type === "AAAA") {
    return server.ipv6Address;
  }
  return target;
}

export function createHcloudInventory(
  intent: EnvironmentIntent,
  provider: pulumi.ProviderResource,
): pulumi.Output<PulumiInventory> {
  const invokeOptions: pulumi.InvokeOutputOptions = { provider };
  const expectedArchitecture = intent.architecture === "amd64" ? "x86" : "arm";
  const location = hcloud.getLocationOutput({ name: intent.region }, invokeOptions);
  const serverType = hcloud.getServerTypeOutput({ name: intent.server_type }, invokeOptions);
  const image = hcloud.getImageOutput(
    {
      name: intent.os_image,
      withArchitecture: expectedArchitecture,
      withStatuses: ["available"],
    },
    invokeOptions,
  );
  const sshKeys = pulumi.all(
    intent.ssh_key_refs.map((reference) => {
      const numericId = /^[1-9][0-9]*$/.test(reference) ? Number(reference) : undefined;
      const args = numericId !== undefined && Number.isSafeInteger(numericId) ? { id: numericId } : { name: reference };
      return hcloud.getSshKeyOutput(args, invokeOptions);
    }),
  );
  const zone =
    intent.dns_provider_ref === "hcloud" && intent.dns_records.length > 0
      ? (() => {
          const reference = intent.dns_zone_ref;
          if (reference === null) {
            throw new Error("HCloud DNS records require a confirmed zone reference");
          }
          const numericId = /^[1-9][0-9]*$/.test(reference) ? Number(reference) : undefined;
          const args = numericId !== undefined && Number.isSafeInteger(numericId) ? { id: numericId } : { name: reference };
          return hcloud.getZoneOutput(args, invokeOptions);
        })()
      : pulumi.output(undefined);

  return pulumi
    .all([location, serverType, image, sshKeys, zone])
    .apply(([observedLocation, observedType, observedImage, observedKeys, observedZone]) => {
      const preflight = validateHcloudPreflight(
        intent,
        observedLocation,
        observedType,
        observedImage,
        observedKeys,
        observedZone,
      );
      const dnsZoneId = preflight.dnsZoneId;
      if (preflight.dnsGroups.length > 0 && dnsZoneId === undefined) {
        throw new Error("HCloud DNS records require a validated existing zone");
      }

      const labels = resourceLabels(intent, "platform");
      const serverName = `anitrend-${intent.environment}-host`;
      const resourceOpts = protectedOptions(intent, provider);
      const networkResources = intent.network_cidrs.map((networkIntent) => {
        const network = new hcloud.Network(
          `network-${networkIntent.name}`,
          {
            name: `anitrend-${intent.environment}-${networkIntent.name}`,
            ipRange: networkIntent.cidr,
            deleteProtection: intent.environment === "production",
            labels: { ...labels, "anitrend.platform.resource": `network-${networkIntent.name}` },
          },
          resourceOpts,
        );
        const subnet = new hcloud.NetworkSubnet(
          `subnet-${networkIntent.name}`,
          {
            networkId: network.id.apply((id) => Number(id)),
            networkZone: preflight.networkZone,
            ipRange: networkIntent.subnet_cidr,
            type: "cloud",
          },
          resourceOpts,
        );
        return { intent: networkIntent, network, subnet };
      });
      const firewall = new hcloud.Firewall(
        "platform-firewall",
        {
          name: `anitrend-${intent.environment}-firewall`,
          rules: firewallRules(intent),
          labels: { ...labels, "anitrend.platform.resource": "firewall" },
        },
        resourceOpts,
      );
      const server = new hcloud.Server(
        "platform-server",
        {
          name: serverName,
          location: intent.region,
          serverType: intent.server_type,
          image: intent.os_image,
          sshKeys: intent.ssh_key_refs,
          publicNets: [{ ipv4Enabled: true, ipv6Enabled: true }],
          firewallIds: [firewall.id.apply((id) => Number(id))],
          networks: [],
          deleteProtection: intent.environment === "production",
          rebuildProtection: intent.environment === "production",
          labels: { ...labels, "anitrend.platform.resource": "server" },
        },
        resourceOpts,
      );
      const serverNetworks = networkResources.map(({ intent: networkIntent, subnet }) => ({
        intent: networkIntent,
        resource: new hcloud.ServerNetwork(
          `server-network-${networkIntent.name}`,
          {
            serverId: server.id.apply((id) => Number(id)),
            subnetId: subnet.id,
            aliasIps: [],
          },
          resourceOpts,
        ),
      }));
      const volumeResources = intent.volumes.map((volumeIntent) => {
        const volume = new hcloud.Volume(
          `volume-${volumeIntent.id_ref}`,
          {
            name: `anitrend-${intent.environment}-${volumeIntent.id_ref}`,
            location: intent.region,
            size: volumeIntent.size_gb,
            format: "ext4",
            deleteProtection: intent.environment === "production" || volumeIntent.protected,
            labels: { ...labels, "anitrend.platform.resource": `volume-${volumeIntent.id_ref}` },
          },
          protectedOptions(intent, provider, intent.safety_policy.protect_resources || volumeIntent.protected),
        );
        const attachment = new hcloud.VolumeAttachment(
          `volume-attachment-${volumeIntent.id_ref}`,
          {
            serverId: server.id.apply((id) => Number(id)),
            volumeId: volume.id.apply((id) => Number(id)),
            automount: false,
          },
          protectedOptions(intent, provider, intent.safety_policy.protect_resources || volumeIntent.protected),
        );
        return { intent: volumeIntent, volume, attachment };
      });
      const dnsResources =
        dnsZoneId === undefined
          ? []
          : preflight.dnsGroups.map((group) => ({
              group,
              resource: new hcloud.ZoneRrset(
                `dns-${group.name}-${group.type.toLowerCase()}`,
                {
                  zone: dnsZoneId,
                  name: group.name,
                  type: group.type,
                  ttl: group.ttl,
                  records: group.targets.map((target) => ({ value: dnsTarget(group, target, server) })),
                  changeProtection: intent.environment === "production",
                  labels: { ...labels, "anitrend.platform.resource": `dns-${group.name}-${group.type.toLowerCase()}` },
                },
                resourceOpts,
              ),
            }));

      const identities: pulumi.Output<PulumiResourceIdentity>[] = [
        server.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: "server", provider_id: providerId, kind: "server" })),
        firewall.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: "firewall", provider_id: providerId, kind: "firewall" })),
      ];
      for (const { intent: networkIntent, network, subnet } of networkResources) {
        identities.push(network.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `network:${networkIntent.name}`, provider_id: providerId, kind: "network" })));
        identities.push(subnet.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `subnet:${networkIntent.name}`, provider_id: providerId, kind: "subnet" })));
      }
      for (const { intent: networkIntent, resource: network } of serverNetworks) {
        identities.push(network.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `server-network:${networkIntent.name}`, provider_id: providerId, kind: "server_network" })));
      }
      for (const { intent: volumeIntent, volume, attachment } of volumeResources) {
        identities.push(volume.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `volume:${volumeIntent.id_ref}`, provider_id: providerId, kind: "volume" })));
        identities.push(attachment.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `volume-attachment:${volumeIntent.id_ref}`, provider_id: providerId, kind: "volume_attachment" })));
      }
      for (const { group, resource } of dnsResources) {
        identities.push(resource.id.apply((providerId): PulumiResourceIdentity => ({ logical_id: `dns-rrset:${group.name}:${group.type}`, provider_id: providerId, kind: "dns_rrset" })));
      }

      const host: pulumi.Output<PulumiHostInventory> = pulumi
        .all([
          server.id,
          server.name,
          server.ipv4Address,
          server.ipv6Address,
          pulumi.all(serverNetworks.map(({ resource }) => resource.ip)),
        ])
        .apply(([resourceId, name, ipv4, ipv6, privateAddresses]): PulumiHostInventory => ({
          resource_id: resourceId,
          name,
          bootstrap_user: intent.bootstrap_user,
          public_ipv4: ipv4 || null,
          public_ipv6: ipv6 || null,
          private_addresses: privateAddresses,
          region: intent.region,
          server_type: intent.server_type,
          architecture: intent.architecture,
          os_image: intent.os_image,
          ssh_key_refs: intent.ssh_key_refs,
          expected_host_identity_ref: intent.target_host_identity_ref,
        }));
      const volumes: pulumi.Output<PulumiVolumeInventory[]> = pulumi.all(
        volumeResources.map(({ intent: volumeIntent, volume }) =>
          pulumi.all([volume.id, volume.linuxDevice]).apply(([resourceId, linuxDevice]): PulumiVolumeInventory => ({
            resource_id: resourceId,
            reference: volumeIntent.id_ref,
            linux_device: linuxDevice,
            filesystem: "ext4",
            mount_path: volumeIntent.mount_path,
            size_gb: volumeIntent.size_gb,
            data_classification: volumeIntent.data_classification,
            protected: intent.environment === "production" || volumeIntent.protected,
          })),
        ),
      );

      return pulumi
        .all([
          pulumi.all(identities),
          pulumi.all(networkResources.map(({ network }) => network.id)),
          pulumi.all([firewall.id]),
          host,
          volumes,
        ])
        .apply(([resourceIds, networkIds, firewallIds, inventoryHost, inventoryVolumes]): PulumiInventory => ({
          schema_version: "anitrend.platform.pulumi-inventory.v1",
          environment: intent.environment,
          stack_identity: pulumi.getProject() + "/" + pulumi.getStack(),
          provider: "hcloud",
          resource_ids: resourceIds,
          network_ids: networkIds,
          firewall_ids: firewallIds,
          firewall_policy: {
            ssh_source_cidrs: intent.ssh_source_cidrs,
            public_routes: intent.public_routes,
            private_routes: intent.private_routes,
          },
          hosts: [inventoryHost],
          volumes: inventoryVolumes,
          architecture: intent.architecture,
          image_ref: intent.os_image,
          native_execution: true,
          budget_limit_eur: intent.budget_limit_eur,
          estimated_monthly_cost_eur: intent.estimated_monthly_cost_eur,
          cost_estimate_ref: intent.cost_estimate_ref,
          ttl_hours: intent.ttl_hours,
          readiness: "ready",
        }));
    });
}
