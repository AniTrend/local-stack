# Primary references

Reviewed 2026-10-24 UTC. Provider/product documentation can change: implementations must pin tested releases and confirm the pinned runtime's API/behaviour. These links support capabilities and limitations; AniTrend-specific design choices are recorded in the ADR.

| ID | Primary source | Relevance |
|---|---|---|
| S01 | [Hcloud provider and resources](https://www.pulumi.com/registry/packages/hcloud/) | Existing Pulumi provider; does not make workloads managed services. |
| S02 | [Pulumi Docker provider](https://www.pulumi.com/registry/packages/docker/) | Local real-resource lab provider; separate from hcloud. |
| S03 | [Pulumi mock testing](https://www.pulumi.com/docs/iac/guides/testing/unit/) | Mocks do not run the full engine or prove provider behaviour. |
| S04 | [Pulumi integration testing](https://www.pulumi.com/docs/iac/guides/testing/integration/) | Provision disposable real resources to prove lifecycle. |
| S05 | [Pulumi state backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends/) | Separate durable production state from disposable local state. |
| S06 | [Pulumi protect option](https://www.pulumi.com/docs/iac/concepts/resources/options/protect/) | Guard production resources against deletion; not a backup. |
| S07 | [Ansible check mode](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html) | Simulation has module-dependent coverage; require real convergence. |
| S08 | [Molecule Docker example](https://docs.ansible.com/projects/molecule/examples/docker/) | Create, converge, verify and destroy container targets; pin supported APIs. |
| S09 | [Dokploy installation](https://docs.dokploy.com/docs/core/installation) | Release-specific installer, Docker setup and ports 80/443/3000. |
| S10 | [Dokploy deployment options](https://docs.dokploy.com/docs/core/deployment-options) | Single host, independent remote hosts and Swarm nodes are different topologies. |
| S11 | [Dokploy Compose](https://docs.dokploy.com/docs/core/docker-compose) | Compose/Stack modes, env injection, persistent file mounts and named-volume backup limits. |
| S12 | [Dokploy Compose API](https://docs.dokploy.com/docs/api/compose) | Inspect pinned server API for create/update/deploy and deployment status integration. |
| S13 | [Dokploy auto deploy](https://docs.dokploy.com/docs/core/auto-deploy) | Webhook/API triggers; avoid bypassing the promotion workflow. |
| S14 | [Dokploy platform backups](https://docs.dokploy.com/docs/core/backups) | Dokploy database and /etc/dokploy need recovery independent of application data. |
| S15 | [Dokploy volume backups](https://docs.dokploy.com/docs/core/volume-backups) | Named-volume backup support; database consistency requires a database-aware method. |
| S16 | [Tailscale GitHub Action](https://tailscale.com/docs/integrations/github/github-action) | Ephemeral runners, scoped tags and workload identity federation. |
| S17 | [Hetzner firewall FAQ](https://docs.hetzner.com/cloud/firewalls/faq/) | Cloud Firewall does not filter private-network traffic. |
| S18 | [Docker firewall behaviour](https://docs.docker.com/engine/network/packet-filtering-firewalls/) | Published ports can bypass ufw's normal INPUT path. |
| S19 | [APISIX deployment modes](https://apisix.apache.org/docs/apisix/deployment-modes/) | File-driven standalone configuration is an optional later simplification. |
| S20 | [Kong DB-less mode](https://developer.konghq.com/gateway/db-less-mode/) | Manager editing, plugin compatibility and decK synchronization limitations. |
| S21 | [Kong OpenID Connect](https://developer.konghq.com/plugins/openid-connect/) | Official OIDC plugin is Enterprise-only. |
| S22 | [PostgreSQL image storage layout](https://hub.docker.com/_/postgres) | PostgreSQL 18+ changes PGDATA/VOLUME defaults; inspect actual server major before migration. |

## Repository evidence

The [current-state inventory](current-state.md) links immutable source paths at [`e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3`](https://github.com/AniTrend/local-stack/commit/e80a48a8b8d7d4d9732840b618e73a2f4b58a1c3). Read the newer default branch before implementing and record any changed assumption. Historical issue closure does not prove host state.

No live host was inspected for this planning publication. The only local runtime probe found the Docker CLI and desktop-linux context, but daemon access was denied by the session environment; Pulumi and Ansible were not found on PATH. No runtime acceptance gate is marked passed.
