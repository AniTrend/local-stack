# Pulumi HCloud provisioning

`infra/pulumi/hcloud/` is the target cloud resource owner. It is separate from the disposable `infra/pulumi/docker/` lab. The HCloud project does not deploy application containers or modify the legacy host.

## Pinned project and stack contract

The project pins `@pulumi/hcloud` 1.43.2, `@pulumi/pulumi` 3.272.0, Ajv 8.20.0, and Node.js 24.22.1 / npm 11.19.1. Install the lockfile-defined packages locally:

```sh
npm ci --prefix infra/pulumi/hcloud
```

Create only the separately named `rehearsal` and `production` stacks. Each stack requires a project-scoped `environment-intent` object validated by `infra/pulumi/shared/environment-intent.schema.json`. The stack name must equal the intent's environment. `bootstrap_user` explicitly identifies the image login account for the first Ansible connection. `platform:hcloud-project-ref` must equal `project_ref`; the secret `hcloud:token` is passed only to the HCloud provider. Configure those values through the approved Pulumi/backend secret flow. Never commit stack configuration, a token, a private key, or decrypted application data.

The local `lab` intent belongs only to the Docker project. Docker mock tests and a local Docker lifecycle are not evidence of HCloud behavior.

## Preflight and resource ownership

Before registering cloud resources, the program resolves the configured HCloud location, server type, available system image, every SSH key reference, and the existing DNS zone when HCloud owns configured DNS records. It rejects architecture mismatches, unavailable or deprecated resources, unknown SSH keys, invalid project/environment selection, invalid CIDRs, unsafe firewall sources, inconsistent route ports, duplicate volume references or mount paths, invalid generated HCloud labels, and an owner estimate above the approved monthly budget ceiling.

The program creates one server and firewall, one HCloud private network and subnet per `network_cidrs` entry, server-network attachments, declared volumes and attachments, and DNS RRsets only when `dns_provider_ref` is exactly `hcloud`. It looks up the configured DNS zone and never creates or assumes ownership of that zone. For HCloud DNS, `target_ref` may use `server:public-ipv4` for an A record or `server:public-ipv6` for an AAAA record; literal matching IP addresses and CNAME target hostnames are also accepted. CNAME targets receive a terminal period when absent, so HCloud treats them as absolute FQDNs. Other DNS providers remain outside this program.

Network and subnet CIDRs are canonical, non-overlapping IPv4 ranges. Firewall source CIDRs for SSH and routes use canonical network-address notation for IPv4 and IPv6, and SSH/private-route sources must not be a default route. Public ingress is limited to TCP ports 80 and 443. SSH uses its separate explicit `ssh_source_cidrs`; private routes also reject a global source. Unlisted inbound traffic is dropped by default. HCloud firewall egress remains provider-default allow-all because the intent contract has no outbound allowlist. Do not apply rehearsal or production resources until G0 records required outbound destinations and an authorized egress policy. HCloud Cloud Firewalls do not filter private-network traffic.

Production resources use Pulumi protection and provider-side delete protection where HCloud supports it. Changes to server type or image are marked as replacements; production protection blocks those replacements. Rehearsal requires a positive `ttl_hours` and permits a reviewed destroy, but the value does not schedule or perform automatic expiry. An operator must schedule cleanup and verify it. Production requires a non-null approved budget and an owner-supplied monthly estimate that does not exceed the limit. HCloud provider 1.43.2 does not provide a price lookup in this program, so the estimate is not independently calculated or verified. Do not treat this comparison as a provider billing cap.

Each server supports at most 16 volumes, with sizes from 10 GB to 10,000 GB and 10,000 GB aggregate capacity. Volumes are created with the declared size and `ext4` format, then attached without provider automount. Pulumi exports the provider device path and intended mount path for Ansible; it does not mount or initialize the filesystem in the host. Ansible owns host mount configuration. A volume's `protected` intent and production policy prevent deletion where supported.

## Inventory and trust boundary

The `inventory` export is validated against `infra/pulumi/shared/pulumi-inventory.schema.json` before publication. It includes stable provider IDs, host addresses and bootstrap user, private addresses, architecture, image reference, SSH key references and target identity reference, the validated inbound firewall policy, and volume device, filesystem and mount path. It excludes the HCloud token, SSH public-key material, and private keys.

`readiness: ready` means the Pulumi resource outputs and HCloud preflight checks completed. It does not prove the guest is reachable, the operating system has converged, or the SSH host key has been verified. `target_host_identity_ref` is an external reference for the Ansible trust step, not a fingerprint attested by Pulumi.

P1-03 consumes this inventory with the separate versioned trust record validated by `infra/pulumi/shared/ssh-host-trust.schema.json`. The adapter requires exact environment, identity-reference, address and SHA-256 fingerprint matches, then writes a mode-0600 `known_hosts` file and uses `StrictHostKeyChecking=yes`. `host_key` pins one exact key; `host_ca` writes an `@cert-authority` entry scoped to the exact address and requires the VM to present a certificate signed by that CA. Never establish trust with `ssh-keyscan`.

For HCloud, bootstrap host-key trust through the authenticated [Hetzner VNC console](https://docs.hetzner.com/cloud/servers/getting-started/vnc-console/): inspect `/etc/ssh/ssh_host_ed25519_key.pub` and its fingerprint with `ssh-keygen -lf`, then store the verified public record under the configured identity reference. For the lab-VM variant, use the VM owner's authenticated hypervisor or console path. The adapter does not connect to the host, fetch keys, or mutate the VM.

## State and preview

The ADR default is Pulumi Cloud. `infra/pulumi/hcloud/Pulumi.yaml` pins `https://api.pulumi.com`, and the intent validator requires `state_backend_ref` to use the `pulumi-cloud:` scheme. The preview wrapper verifies the pinned CLI and current Pulumi Cloud backend with `pulumi whoami --verbose`. It does not log in, create a stack, or supply credentials. The reference is not matched to a specific account or organization; the wrapper verifies the backend host, not the logged-in owner. Use an identity scoped to the intended organization and confirm the stack and `platform:hcloud-project-ref` before any authorized update. Keep state access restricted and retain an independent recovery identity. Pulumi Cloud maintains checkpoint history; use its documented recovery workflow and `pulumi stack export` / `pulumi stack import` only under restricted evidence handling. State exports can contain sensitive infrastructure metadata. Never commit exports, credentials, or stack state.

### Bootstrap, recovery and rotation

On a new operator workstation, install the pinned Pulumi CLI and authenticate to Pulumi Cloud through the approved identity flow. Confirm `pulumi whoami --verbose` reports the expected Pulumi Cloud account before creating or selecting the separate `rehearsal` and `production` stacks. The project URL is fixed in `Pulumi.yaml`; do not substitute a local file backend. See the [Pulumi state and backend guide](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) and [`pulumi whoami` command reference](https://www.pulumi.com/docs/iac/cli/commands/pulumi_whoami/).

Store `environment-intent`, `platform:hcloud-project-ref`, and the secret `hcloud:token` separately in each stack. The token must be entered through the approved secret flow, not a plaintext command argument or checked-in file. Run updates through one authorized identity at a time. The mock suite and disposable local lab do not verify Pulumi Cloud locking or concurrent update recovery; those remain provider/backend validation gates.

For recovery, use Pulumi Cloud checkpoint history first. Export state only to restricted evidence storage, preserve the encrypted stack configuration separately, and restore with the documented `pulumi stack import` workflow followed by a reviewed diff preview. Never treat the exported state as a backup of the guest's application data. Rotate the HCloud token by installing the replacement as a Pulumi secret, confirming its project reference and read-only preview, then revoking the old token under the approved credential procedure.

Use a preview before any authorized HCloud update:

```sh
make platform-preview ENV=rehearsal
make platform-preview ENV=production
```

The wrapper verifies the pinned CLI and Pulumi Cloud backend, then invokes `pulumi preview --diff --non-interactive --stack <environment>` from the HCloud project. It does not run `up`, create a stack, log in, or supply credentials. The operator must already have the intended Pulumi Cloud identity, stack, secret configuration, HCloud token, and approved credential context. The diff identifies creates, updates, replacements, and deletes. A preview is not proof of provider lifecycle, guest readiness, backup restoration, or authorization to apply it.

Offline validation uses:

```sh
make platform-pulumi-test ENV=lab
make platform-preview ENV=lab
```

The first command runs Docker and HCloud Pulumi mock/unit tests plus platform Python tests. The second previews only an already-created local Docker lab stack and requires the safe local Docker prerequisites. Neither command provisions HCloud resources. P4 is the first issue authorized to perform the real HCloud rehearsal after its prerequisites and approval gates pass.
