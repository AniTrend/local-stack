export type EnvironmentName = "rehearsal" | "production";

export type ProviderName = "hcloud";

export interface NetworkCidrIntent {
  name: string;
  cidr: string;
  subnet_cidr: string;
  purpose: string;
}

export interface VolumeIntent {
  id_ref: string;
  size_gb: number;
  mount_path: string;
  data_classification: string;
  protected: boolean;
}

export interface RouteIntent {
  hostname: string;
  service_ref: string;
  port: number;
  protocol: "http" | "https" | "tcp" | "udp";
  source_cidrs: string[];
}

export interface DnsRecordIntent {
  hostname: string;
  record_type: "A" | "AAAA" | "CNAME";
  target_ref: string;
  ttl_seconds: number;
}

export interface EnvironmentSafetyPolicy {
  protect_resources: boolean;
  allow_destroy: boolean;
  require_environment_approval: boolean;
  deny_pull_request_mutations: boolean;
}

export interface EnvironmentIntent {
  schema_version: "anitrend.platform.environment-intent.v1";
  environment: EnvironmentName;
  provider: ProviderName;
  project_ref: string;
  region: string;
  server_type: string;
  architecture: "amd64" | "arm64";
  os_image: string;
  network_cidrs: NetworkCidrIntent[];
  volumes: VolumeIntent[];
  ssh_key_refs: string[];
  bootstrap_user: string;
  ssh_source_cidrs: string[];
  public_routes: RouteIntent[];
  private_routes: RouteIntent[];
  dns_provider_ref: string | null;
  dns_zone_ref: string | null;
  dns_records: DnsRecordIntent[];
  private_hostnames: string[];
  certificate_strategy_ref: string | null;
  tailnet_grants_ref: string | null;
  state_backend_ref: string;
  backup_destination_ref: string;
  backup_retention_days: number;
  credential_refs: string[];
  recovery_credential_refs: string[];
  rpo_hours: number;
  rto_minutes: number;
  maintenance_window_ref: string;
  maximum_downtime_minutes: number;
  rollback_thresholds: string[];
  writer_job_map_ref: string;
  source_host_identity_ref: string;
  target_host_identity_ref: string;
  deployment_owner_map_ref: string;
  deployment_freeze_steps_ref: string;
  service_dependency_map_ref: string;
  database_runtime_facts_ref: string;
  gateway_policy_export_ref: string;
  external_provider_map_ref: string;
  backup_restore_matrix_ref: string;
  budget_limit_eur: number;
  estimated_monthly_cost_eur: number;
  cost_estimate_ref: string;
  ttl_hours: number | null;
  allowed_docker_contexts: string[];
  safety_policy: EnvironmentSafetyPolicy;
}

export interface PulumiResourceIdentity {
  logical_id: string;
  provider_id: string;
  kind: "server" | "network" | "subnet" | "firewall" | "server_network" | "volume" | "volume_attachment" | "dns_rrset";
}

export interface PulumiHostInventory {
  resource_id: string;
  name: string;
  bootstrap_user: string;
  public_ipv4: string | null;
  public_ipv6: string | null;
  private_addresses: string[];
  region: string;
  server_type: string;
  architecture: "amd64" | "arm64";
  os_image: string;
  ssh_key_refs: string[];
  expected_host_identity_ref: string;
}

export interface PulumiVolumeInventory {
  resource_id: string;
  reference: string;
  linux_device: string;
  filesystem: "ext4";
  mount_path: string;
  size_gb: number;
  data_classification: string;
  protected: boolean;
}

export interface PulumiFirewallPolicy {
  ssh_source_cidrs: string[];
  public_routes: RouteIntent[];
  private_routes: RouteIntent[];
}

export interface PulumiInventory {
  schema_version: "anitrend.platform.pulumi-inventory.v1";
  environment: "rehearsal" | "production";
  stack_identity: string;
  provider: "hcloud";
  resource_ids: PulumiResourceIdentity[];
  network_ids: string[];
  firewall_ids: string[];
  firewall_policy: PulumiFirewallPolicy;
  hosts: PulumiHostInventory[];
  volumes: PulumiVolumeInventory[];
  architecture: "amd64" | "arm64";
  image_ref: string;
  native_execution: boolean;
  budget_limit_eur: number;
  estimated_monthly_cost_eur: number;
  cost_estimate_ref: string;
  ttl_hours: number | null;
  readiness: "ready" | "blocked" | "failed";
}

export interface PulumiLabVmHostInventory {
  resource_id: string;
  name: string;
  bootstrap_user: string;
  connect_address: string;
  architecture: "amd64" | "arm64";
  os_image: string;
  expected_host_identity_ref: string;
}

export interface PulumiLabVmInventory {
  schema_version: "anitrend.platform.pulumi-inventory.lab-v1";
  environment: "lab";
  stack_identity: string;
  provider: "external-vm";
  ssh_source_cidrs: string[];
  hosts: PulumiLabVmHostInventory[];
  volumes: PulumiVolumeInventory[];
  architecture: "amd64" | "arm64";
  image_ref: string;
  native_execution: true;
  readiness: "ready" | "blocked" | "failed";
}

export type VersionedHostInventory = PulumiInventory | PulumiLabVmInventory;
