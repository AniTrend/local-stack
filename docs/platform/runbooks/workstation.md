# Workstation onboarding and local validation runbook

Audience: a contributor with no tools installed and no system accounts set up. This runbook reaches a working local validation environment (validation tiers T0 and T1 from [the validation contract](../validation.md)) on either a clean Ubuntu x86_64 workstation or a macOS arm64 (Apple Silicon) workstation.

Privilege and scope: most steps run inside your user account and the repository. The exceptions are explicitly labelled: installing the system prerequisites (Git packages, Docker Engine, pyenv build dependencies) uses `sudo apt` on Ubuntu and admin rights on macOS, and adding your user to the `docker` group requires logging out and back in. Every Docker, Pulumi, and Ansible action is scoped to one explicitly allowlisted local Docker daemon plus repo-local state.

Read first, in order:

1. [Platform README](../README.md) (phases, gates, authorization boundary).
2. [ADR 0001: platform ownership](../adr-0001-platform-ownership.md).
3. [Validation tiers and command contract](../validation.md).
4. [Current state and inventory gaps](../current-state.md).

Sibling runbooks for later stages: [inventory-and-host.md](inventory-and-host.md) (P0 live inventory and P1 host/VM acceptance for #653 to #656), [delivery.md](delivery.md) (release delivery and promotion), [migration.md](migration.md) (rehearsal, cutover, recovery).

Authorization boundary for this document: everything here is local, free, and reversible. It authorizes no cloud spend, no live production mutation, and no destructive action against any existing host, container, or volume.

## Glossary

| Term | Meaning |
|---|---|
| Validation tier | T0 static/mock checks, T1 local Docker resources, T2 full Linux VM, T3 disposable Hetzner, T4 production canary. See [validation.md](../validation.md). |
| Docker context | A named Docker CLI endpoint configuration (`docker context ls`). The lab requires you to select one explicitly and never changes your active context. |
| Fail closed | A missing prerequisite produces a nonzero exit and a specific message; it is never converted into a pass. |
| Lab run ID | `YYYYMMDDTHHMMSSZ-<8 hex>` label naming one lab lifecycle; resources carry it as Docker labels. |
| Restricted storage | An encrypted, access-controlled location outside this public repository for keys, raw exports, and evidence containing secrets. |
| P0 / P1 work items | P0-01 is issue [#653](https://github.com/AniTrend/local-stack/issues/653) (live inventory). P1-01 to P1-03 are issues [#654](https://github.com/AniTrend/local-stack/issues/654), [#655](https://github.com/AniTrend/local-stack/issues/655), [#656](https://github.com/AniTrend/local-stack/issues/656) (lab, HCloud program, host baseline). |

## What already exists and what does not

Implemented and reviewed on this branch (head of PR [#671](https://github.com/AniTrend/local-stack/pull/671), stacked on [#670](https://github.com/AniTrend/local-stack/pull/670) and [#669](https://github.com/AniTrend/local-stack/pull/669)):

- `make platform-doctor ENV=lab`, `platform-lab-up`, `platform-lab-test`, `platform-lab-down`, `platform-pulumi-test ENV=lab`, `platform-preview ENV=lab`, `platform-ansible-test ENV=lab`, `platform-host-verify ENV=lab TIER=vm`.
- `make platform-evidence-validate ENV=lab TIER=docker|vm MANIFEST=FILE COMMIT=FULL_40_HEX_SHA` validates completed evidence records against their pinned schemas (scope labels `docker-lab-lifecycle` or `host-baseline`); it checks recorded evidence only, never authenticity, current host state, or G0 to G6 gate approval.
- Pinned toolchain files: `.node-version`, `.python-version`, `tools/platform/requirements.lock` (hash-locked), `ansible/requirements.yml`, `tools/platform/pulumi-version.txt`, `infra/pulumi/docker/package.json`, `infra/pulumi/hcloud/package.json`, `infra/pulumi/docker/images.lock.json`.

Not integrated into this checkout yet: the P0 inventory collector (`platform-inventory` and `platform-inventory-validate`) is published separately in draft [PR #673](https://github.com/AniTrend/local-stack/pull/673). [Inventory and host, Part A](inventory-and-host.md#part-a-p0-01-live-inventory-reconciliation-653) shows how to obtain and run it without the original workstation. Dokploy integration, delivery, rehearsal and cutover targets remain unimplemented. An unknown Make target on this checkout exits 2; never treat that as a pass or overwrite the P1 Makefile with the separate P0 Makefile.

## Stage 0: accounts, identities, and what you do NOT need yet

The public repository can be cloned over HTTPS and its local lab run without any cloud or GitHub credential. A GitHub identity is needed when you submit changes or use authenticated repository/CI operations. Every other identity below is needed only for a later tier; obtain it from the named owner and store credentials in restricted storage, not in this repository.

| Identity / account | Needed for | Who obtains and authorizes it | Storage and recovery rule | Check / stop condition |
|---|---|---|---|---|
| GitHub account and authenticated Git access | Pushing changes, PRs and authenticated CI evidence access; optional for a public read-only clone | You; repository admin grants the required contribution permissions | Dedicated SSH key mode 0600 or GitHub CLI HTTPS authentication; never put credentials in a clone URL | SSH path: compare GitHub's published host fingerprint, then `ssh -T` must identify the intended account. Public HTTPS read-only clones do not require this |
| Hetzner Cloud project and API token | T3 rehearsal and later only; NOT needed now | Platform owner creates the project and documents independent account recovery; an additional operator is recommended | Token in restricted storage only; never in the repo, shell history, or lab environment | Nothing on Hetzner may be created for this runbook; a paid stage requires its own concrete authorization |
| Pulumi Cloud account and token | `ENV=rehearsal` / `ENV=production` previews and later state (NOT needed for the local lab, which uses a disposable file backend) | Platform owner; local lab never touches it | Token stored per the Pulumi CLI's own credential store after `pulumi login`; recovery uses the org's documented member recovery | Do not export `PULUMI_ACCESS_TOKEN` while running any `make platform-*` command; the lab refuses cloud credentials in the environment |
| DNS provider / zone owner | P1-02 DNS records and later phases | Zone owner records provider, zone, and record policy | Credential references only; secrets in restricted storage | No DNS change is authorized by this runbook |
| Tailscale tailnet identity, ACL tag, auth key | `make platform-host-verify ENV=lab TIER=vm` | Tailnet admin defines the tag and issues one scoped, short-lived auth key | Auth key is single-line, used through a private env file; revoke after the run | If no admin can approve a tag, the VM tier stays blocked, which is valid blocked evidence, not a failure to work around |
| SOPS + age identity | P2-03 secret delivery, not now | Platform owner; generation is a later runbook step | The age private key never enters this repository or a workstation dotfile shared with others | Nothing here generates or reads it |
| Evidence storage | Any evidence containing secrets | Platform owner designates independent encrypted storage outside the public checkout | Raw dumps stay there; only sanitized facts are committed | If restricted storage does not exist, secret-bearing steps stay blocked |

Independent recovery rule (canonical requirement from [migration-runbook.md](../migration-runbook.md#recovery-dependencies)): recovery must start outside the failed host, and no identity above may depend circularly on a credential it protects (for example, a backup system whose only restore credential lives on the platform it restores). Keep every identity recoverable independently, recommend a second holder per identity, and store secrets in restricted storage, never in this repository.

## Stage 1: Git, GitHub authentication, and the exact revision

Privilege levels in this stage, labelled per step: system package installation (sudo apt on Ubuntu, admin rights on macOS), per-user configuration (git config, ssh-keygen under your account), and repository-local state (`~/Git`). Step 5 mutates only your checkout.

1. Install the base packages (system-level: this step needs sudo on Ubuntu and admin rights on macOS). On Ubuntu 24.04:

   ```sh
   sudo apt-get update
   sudo apt-get install -y git curl ca-certificates openssh-client
   ```

   On macOS, accept the command line tools prompt (`git --version` triggers it) or install Homebrew per [brew.sh](https://brew.sh) and install `git` through it.

2. Configure Git identity locally (no machine-wide settings beyond your own user):

   ```sh
   git config --global user.name "Your Name"
   git config --global user.email "you@example.com"
   ```

3. If you will use SSH or push changes, generate a dedicated SSH key and register its public key in GitHub (Settings, SSH and GPG keys, New SSH key) following [Connecting to GitHub with SSH](https://docs.github.com/en/authentication/connecting-to-github-with-ssh). This step is user-level only. For an anonymous public HTTPS clone, skip it and use the HTTPS block in step 4:

   ```sh
   ssh-keygen -t ed25519 -C "you@example.com platform workstation" -f ~/.ssh/id_ed25519_anitrend
   ```

   Verify GitHub's host identity once before the first real connection; GitHub prints its verified fingerprints, published at [GitHub's SSH key fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints). Compare before typing yes:

   ```sh
   ssh -i ~/.ssh/id_ed25519_anitrend -o IdentitiesOnly=yes -T git@github.com
   ```

   Simpler alternative without any SSH key: install the GitHub CLI ([cli.github.com](https://cli.github.com)) and authenticate HTTPS with `gh auth login`, then clone the HTTPS URL. Pick one path and use it consistently.

4. Clone over SSH (the key file is not a default name, so pass it exactly once via `GIT_SSH_COMMAND`) and pin the same command for all later Git network operations in this checkout:

   ```sh
   mkdir -p ~/Git && cd ~/Git
   GIT_SSH_COMMAND='ssh -i ~/.ssh/id_ed25519_anitrend -o IdentitiesOnly=yes' \
     git clone git@github.com:AniTrend/local-stack.git local-stack
   cd local-stack
   git config core.sshCommand 'ssh -i ~/.ssh/id_ed25519_anitrend -o IdentitiesOnly=yes'
   git status --short --branch
   ```

   Choose this alternative HTTPS block instead of the SSH block if you only need the public checkout. No GitHub account is required for the read-only clone. For later contributions, install the [GitHub CLI](https://cli.github.com) and use its `gh auth login` and `gh auth setup-git` workflows; do not embed a token in the URL.

   ```sh
   mkdir -p "$HOME/Git"
   git clone https://github.com/AniTrend/local-stack.git "$HOME/Git/local-stack"
   cd "$HOME/Git/local-stack"
   git status --short --branch
   ```

5. Select the reviewed feature revision. The P1 PRs form a stack: [#669](https://github.com/AniTrend/local-stack/pull/669) (`feat/platform-lab-654`) implements the lab, [#670](https://github.com/AniTrend/local-stack/pull/670) adds HCloud provisioning, and [#671](https://github.com/AniTrend/local-stack/pull/671) adds the Ansible host/container commands plus this evidence/runbook delivery. The host-verification and container-Ansible targets are not supplied by the predecessor branches. Until this stack merges, use the current #671 head and record its full SHA; do not select the older `11535ba` baseline merely because it is cited as historical evidence.

   ```sh
   git switch feat/platform-ansible-656
   git log --oneline -3   # compare with the currently reviewed PR #671 head
   ```

   Record the full SHA you validated (`git rev-parse HEAD`). If the branch has moved since this runbook was written, re-read the PR descriptions for the current stacking and re-run from the new head; do not mix branches in one checkout.

## Stage 2: Docker Engine and explicit local context selection

The lab talks to one explicitly allowlisted local Docker context over a local socket. It never changes your active context, never initializes Swarm, and never installs anything into the daemon beyond the images it pulls itself.

1. Ubuntu x86_64 (system-level: sudo apt, machine-wide install, plus a group-membership change that needs you to log out and back in): install Docker Engine from Docker's official apt repository following [Install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/). This installs `docker-ce`, the CLI, containerd, and the `docker compose` plugin. Add your user to the `docker` group per that page's post-install steps, and confirm:

   ```sh
   docker version --format '{{.Client.Version}} / {{.Server.Version}}'
   docker compose version
   docker context ls
   ```

   The default context endpoint must be a local Unix socket such as `unix:///var/run/docker.sock`.

2. macOS arm64 (system-level: the installer needs admin rights and an app restart of Docker Desktop): install Docker Desktop for Apple Silicon per [docs.docker.com](https://docs.docker.com/desktop/setup/install/mac-install/). Its context is normally `desktop-linux` with endpoint `unix:///Users/<you>/.docker/run/docker.sock`. Verify with `docker context inspect desktop-linux`. Note: the repository's legacy `stackctl` CI setup action supports Linux x86_64 runners only (`.github/actions/setup-stackctl/action.yml`), so legacy generated-stack drift checks run in CI for you; that action is irrelevant to the platform lab.

3. Select the context explicitly for every lab shell. Replace `default` with the locally inspected context name from step 1 (never copy a production, remote, or otherwise meaningful context name into the allowlist; names containing `prod`, `production`, `legacy`, `rehearsal`, `hcloud`, `hetzner`, or `remote` are refused outright):

   ```sh
   export PLATFORM_DOCKER_CONTEXT=default
   export PLATFORM_ALLOWED_DOCKER_CONTEXTS=default
   ```

4. Confirm the daemon is not in Swarm mode and has room to run the lab (doctor enforces all of this read-only; commands target your selected context explicitly, never the ambient default):

   ```sh
   docker --context "$PLATFORM_DOCKER_CONTEXT" info --format '{{.Swarm.LocalNodeState}}'   # must print: inactive
   docker --context "$PLATFORM_DOCKER_CONTEXT" info --format '{{.NCPU}} {{.MemTotal}}'      # doctor requires >= 2 CPUs and >= 2 GiB
   df -h .                                             # doctor requires >= 2 GiB free in the repo filesystem
   ```

Never run `docker swarm init`, `docker system prune`, or any destructive prune on this daemon as part of platform work. If your everyday daemon fails these checks, create a separate local daemon or context rather than weakening an existing one.

## Stage 3: pinned repo-local toolchain

Versions are pinned in the repository and verified by `platform-doctor`. The Makefile prefers, in order: the virtualenv `.venv-platform/bin`, `.tools/platform/node/bin` for Node/npm, and `.tools/platform/bin` for Pulumi; it falls back to `PATH` tools only when the repo-local ones are absent. All commands in this stage run in the workstation shell and write only inside the repository checkout (plus the per-user version manager below). Nothing here touches the Docker daemon.

Pins to expect (verify against the live files, they change by PR):

| Tool | Pin | Source of truth |
|---|---|---|
| Python | 3.14.9 | `.python-version` |
| Node.js | 24.22.1 | `.node-version` |
| npm | 11.19.1 | `packageManager` in both `infra/pulumi/*/package.json` |
| Pulumi CLI | 3.272.0 | `tools/platform/pulumi-version.txt` |
| ansible-core / molecule / molecule-plugins[docker] | 2.21.5 / 26.10.0 / 26.10.12 | `tools/platform/requirements.in` |
| pytest / PyYAML / jsonschema / cryptography | 8.4.2 / 6.0.3 / 4.25.1 / 50.0.2 | `tools/platform/requirements.in` |
| Ansible collections | ansible.posix 2.2.2, community.docker 5.0.0, community.general 13.5.0, community.library_inventory_filtering_v1 1.1.5 | `ansible/requirements.yml` |
| Pulumi libraries | @pulumi/pulumi 3.272.0, @pulumi/docker 5.2.0, @pulumi/hcloud 1.43.2, ajv 8.20.0, ajv-formats 3.0.1 | both `package.json` files |
| Lab SSH fixture image | `lscr.io/linuxserver/openssh-server@sha256:0f535b0faa7448511b23528165e9fbd4f1fe563b861b3dcaa5ddb0ddbfe2254c`, port 2222, platforms linux/amd64 and linux/arm64 | `infra/pulumi/docker/images.lock.json` |
| Tailscale on the VM (later tier) | 1.104.2 with per-arch SHA-256 checksums | `ansible/roles/platform_tailscale/defaults/main.yml` |

1. Per-user Python 3.14.9 via pyenv (per-user version manager; no machine-wide default change; no `pyenv shell` needed anywhere, the checkout's committed `.python-version` selects the version automatically).

   Ubuntu (system-level: this apt line needs sudo; it is the pyenv wiki's Ubuntu build dependency set):

   ```sh
   sudo apt-get update
   sudo apt-get install -y make build-essential libssl-dev zlib1g-dev libbz2-dev \
     libreadline-dev libsqlite3-dev wget curl llvm libncursesw5-dev xz-utils \
     tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev
   curl -fsSL https://pyenv.run | bash
   ```

   macOS arm64 (user-level Homebrew installs):

   ```sh
   brew install pyenv openssl readline sqlite3 xz zlib tcl-tk
   ```

   Activate pyenv in your own shell profile (user-level; append these three lines to `~/.bashrc` on Ubuntu or `~/.zshrc` on macOS, then open a new shell):

   ```sh
   export PYENV_ROOT="$HOME/.pyenv"
   export PATH="$PYENV_ROOT/bin:$PATH"
   eval "$(pyenv init -)"
   ```

   Install the pinned Python and verify it resolves inside the checkout:

   ```sh
   pyenv install 3.14.9
   cd ~/Git/local-stack
   pyenv version          # expect: 3.14.9 (selected by the committed .python-version)
   python3.14 --version   # expect: Python 3.14.9
   ```

2. Hash-locked Python environment inside the checkout:

   ```sh
   python3.14 -m venv .venv-platform
   .venv-platform/bin/python -m pip install --require-hashes -r tools/platform/requirements.lock
   ```

   `--require-hashes` makes pip refuse any package whose pinned SHA-256 is missing from `tools/platform/requirements.lock`.

3. Ansible collections into the ignored repo-local directory:

   ```sh
   export PLATFORM_ANSIBLE_COLLECTIONS_PATH=.tools/platform/collections
   export ANSIBLE_COLLECTIONS_PATH="$PLATFORM_ANSIBLE_COLLECTIONS_PATH"
   .venv-platform/bin/ansible-galaxy collection install -p "$PLATFORM_ANSIBLE_COLLECTIONS_PATH" -r ansible/requirements.yml
   ```

   The doctor fails if any pinned collection is missing or a different version is installed.

4. Repo-local pinned Node.js (choose the recipe for your platform; both extract into the checkout so the Makefile finds `bin/node` and `bin/npm` at `.tools/platform/node/bin`). Verify the download's SHA-256 against the official `SHASUMS256.txt` from [nodejs.org/dist/v24.22.1/](https://nodejs.org/dist/v24.22.1/) before extracting; that is the same manifest the official installers and version managers verify.

   Ubuntu x86_64 (repo root, sha256sum):

   ```sh
   mkdir -p .tools/platform/node
   curl -fsSLO https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz
   curl -fsSLO https://nodejs.org/dist/v24.22.1/SHASUMS256.txt
   printf '%s\n' "$(grep 'node-v24.22.1-linux-x64.tar.xz$' SHASUMS256.txt)" | sha256sum -c -
   tar -xJf node-v24.22.1-linux-x64.tar.xz --strip-components=1 -C .tools/platform/node
   .tools/platform/node/bin/node --version   # expect v24.22.1
   ```

   macOS arm64 (repo root, shasum):

   ```sh
   mkdir -p .tools/platform/node
   curl -fsSLO https://nodejs.org/dist/v24.22.1/node-v24.22.1-darwin-arm64.tar.gz
   curl -fsSLO https://nodejs.org/dist/v24.22.1/SHASUMS256.txt
   printf '%s\n' "$(grep 'node-v24.22.1-darwin-arm64.tar.gz$' SHASUMS256.txt)" | shasum -a 256 -c -
   tar -xzf node-v24.22.1-darwin-arm64.tar.gz --strip-components=1 -C .tools/platform/node
   .tools/platform/node/bin/node --version   # expect v24.22.1
   ```

   Alternative without any download, if some Node >= 22 is already on your `PATH`: prefix pinned runs with the exact form CI uses, for example `npm exec --yes --package=node@24.22.1 --package=npm@11.19.1 -- npm ci --prefix infra/pulumi/docker`.

5. Checksum-verified Pulumi distribution (choose the recipe for your platform). Digests as reviewed in [local-lab.md](../local-lab.md#host-setup); verify before extracting:

   | Host | Asset | SHA-256 |
   |---|---|---|
   | Linux x86_64 | `pulumi-v3.272.0-linux-x64.tar.gz` | `58d545f2b98761051922008ebd381ecef95484d7f7a5ff7faa15d7a780ea84f6` |
   | Linux arm64 | `pulumi-v3.272.0-linux-arm64.tar.gz` | `4f0741901b8982c4326b702dabf483c63d2cf77c88ac42dd752b72541284a534` |
   | macOS x86_64 | `pulumi-v3.272.0-darwin-x64.tar.gz` | `2c11154168e4dc58d43c2b70b0941fa3335d911af2806feac7bf3b8072a5f09a` |
   | macOS arm64 | `pulumi-v3.272.0-darwin-arm64.tar.gz` | `1fb554bf39ad83ba6eef6ecb7ac5a14b8158941ccd97d201837d13dc09806014` |

   Ubuntu x86_64 (repo root, sha256sum):

   ```sh
   curl -fsSLO https://github.com/pulumi/pulumi/releases/download/v3.272.0/pulumi-v3.272.0-linux-x64.tar.gz
   printf '%s  %s\n' 58d545f2b98761051922008ebd381ecef95484d7f7a5ff7faa15d7a780ea84f6 pulumi-v3.272.0-linux-x64.tar.gz | sha256sum -c -
   mkdir -p .tools/platform/bin
   tar -xzf pulumi-v3.272.0-linux-x64.tar.gz -C .tools/platform/bin --strip-components=1
   ```

   macOS arm64 (repo root, shasum):

   ```sh
   curl -fsSLO https://github.com/pulumi/pulumi/releases/download/v3.272.0/pulumi-v3.272.0-darwin-arm64.tar.gz
   printf '%s  %s\n' 1fb554bf39ad83ba6eef6ecb7ac5a14b8158941ccd97d201837d13dc09806014 pulumi-v3.272.0-darwin-arm64.tar.gz | shasum -a 256 -c -
   mkdir -p .tools/platform/bin
   tar -xzf pulumi-v3.272.0-darwin-arm64.tar.gz -C .tools/platform/bin --strip-components=1
   ```

   Extract the whole archive (it includes the `pulumi-language-nodejs` plugin the Makefile needs on `PATH` alongside `pulumi`), not only the CLI binary. If you point `PLATFORM_PULUMI_BIN` elsewhere, keep the matching language plugin available too.

6. Install both Pulumi projects' locked dependencies. First export the repo-local tool directories on `PATH` exactly as the Makefile does (the `npm` launcher is a Node script and needs its own repo-local `node`), pin npm to the exact `packageManager` version, then install:

   ```sh
   export PATH="$PWD/.venv-platform/bin:$PWD/.tools/platform/node/bin:$PWD/.tools/platform/bin:$PATH"
   .tools/platform/node/bin/npm install --global --prefix "$PWD/.tools/platform/node" npm@11.19.1
   .tools/platform/node/bin/npm --version   # expect 11.19.1 (the bundled npm may differ)
   .tools/platform/node/bin/npm ci --prefix infra/pulumi/docker --no-audit --no-fund
   .tools/platform/node/bin/npm ci --prefix infra/pulumi/hcloud --no-audit --no-fund
   ```

   The npm pin overwrites the bundled `bin/npm` inside `.tools/platform/node` only; nothing outside the checkout changes.

## Stage 4: run and clean the local lab (T1)

All commands run from the repository root in the workstation shell. Mutation scope: creates and destroys only the lab's own labelled Docker resources and repo-local state; never touches other containers, volumes, images beyond its pinned fixture, or your active Docker context.

1. In the same shell as Stage 2 step 3, make sure no cloud credential variables are exported (`HCLOUD_TOKEN`, `HETZNER_TOKEN`, `PULUMI_ACCESS_TOKEN`, `SOPS_AGE_KEY`, `TAILSCALE_AUTHKEY`, `DOKPLOY_API_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AZURE_CLIENT_SECRET`, `GOOGLE_APPLICATION_CREDENTIALS`). The doctor and every lab runner refuse to run when any of these is set.

2. Run the lifecycle in order:

   ```sh
   make platform-doctor ENV=lab
   make platform-lab-up ENV=lab
   make platform-lab-test ENV=lab
   make platform-preview ENV=lab
   make platform-lab-down ENV=lab
   ```

   Expected manifestations, all printed by the tools themselves:

   - `platform-doctor` prints a `platform-doctor=pass` report with the selected context, endpoint kind, Docker/Compose versions, host and daemon architectures, `execution_mode=native` or `emulated`, pinned tool versions, installed collection versions, and the fixture image digest. It is read-only.
   - `platform-lab-up` prints a run ID and creates a passphrased file-backend Pulumi stack plus uniquely labelled Docker resources (network, volume, and an SSH fixture container named `anitrend-platform-lab-<run-id>-ssh`), publishing SSH on a reserved loopback port only. It returns after the container's SSH listener is healthy.
   - `platform-lab-test` proves a second identical update is a no-op, verifies real Docker state and loopback-only SSH, then applies a controlled revision-label update. After it passes, `platform-preview` prints a non-mutating diff for the active stack.
   - `platform-lab-down` verifies the Pulumi inventory and Docker ownership labels, destroys the stack's resources, and verifies removal. It intentionally keeps the content-addressed fixture image cached (`keepLocally: true`) and keeps the sanitized manifest.
   - If a run is interrupted, `make platform-lab-up ENV=lab` resumes it only from the same commit and lab-input fingerprint; otherwise `make platform-lab-down ENV=lab` cleans the old stack first. See [local-lab.md](../local-lab.md#run-the-lab).

3. Ownership cleanup check (read-only) after `down`, scoped to your selected context and filtered by the actual labels the lab program and the Ansible runner set (`anitrend.platform.managed-by`, `anitrend.platform.run-id` from `infra/pulumi/docker/lab.ts`; `platform-owner`, `platform-run-id` from the Ansible runner):

   ```sh
   docker --context "$PLATFORM_DOCKER_CONTEXT" ps -a --filter 'label=anitrend.platform.managed-by=pulumi' --filter 'label=anitrend.platform.run-id'
   docker --context "$PLATFORM_DOCKER_CONTEXT" volume ls --filter 'label=anitrend.platform.run-id'
   docker --context "$PLATFORM_DOCKER_CONTEXT" network ls --filter 'label=anitrend.platform.run-id'
   docker --context "$PLATFORM_DOCKER_CONTEXT" ps -a --filter 'label=platform-owner=anitrend-platform-ansible-test' --filter 'label=platform-run-id'
   ```

   These must list nothing from a completed run. The lab container image (`lscr.io/linuxserver/openssh-server` by digest) and the Ansible scenario image `anitrend/platform-ansible:ubuntu-24.04` remain cached by design; removing them is optional `docker rmi` housework, never a `prune`.

4. Container-level Ansible acceptance (still T1):

   ```sh
   make platform-ansible-test ENV=lab
   ```

   This builds the digest-pinned Ubuntu 24.04 scenario image (host networking only during the image build), then runs Molecule on an ordinary bridge container with no published ports, named `platform-ansible-<run-id>-ubuntu-2404` and labelled with an owner/run pair. Before Molecule's initial destroy the runner inspects that exact name and refuses to destroy anything whose ownership labels do not match, so a pre-existing container called `ubuntu-2404` on your daemon is never touched. Expected output ends with Molecule reporting the scenario successful through convergence, idempotence, drift repair, verification, and owned-container cleanup.

## Stage 5: evidence and CI parity

- Every lab run writes a sanitized manifest to `.artifacts/platform/lab/<run-id>/manifest.json` (Git-ignored). It records the source commit, tool versions, architectures, the fixture digest, test outcomes, and cleanup status, and excludes the Docker socket path, passphrases, and private keys. This is the non-secret evidence referenced by [#654](https://github.com/AniTrend/local-stack/issues/654) acceptance.
- GitHub Actions runs the same offline and T1 suite as the `Platform lab offline validation` job of `.github/workflows/ci.yml` on `ubuntu-latest` x86_64: hash-locked Python, pinned Node/npm via `npm exec`, repo-local collections, `platform-pulumi-test`, and the Docker-backed Molecule scenario, uploading non-secret reports. Nothing in CI provisions cloud resources. A macOS workstation therefore gets its native T1 evidence locally and the Linux x86_64 evidence from CI.
- Validate a completed evidence record before citing it. This is record validation only: it proves the manifest is complete, internally consistent, passing, and bound to the exact commit, and it asserts nothing about authenticity, current host state, or any G0 to G6 gate.

  ```sh
  # Set RUN_ID to the exact run ID the lab command printed (format YYYYMMDDTHHMMSSZ-<8 hex>).
  # Docker lab run record (lab-run.v1; the manifest produced by the Stage 4 lifecycle):
  RUN_ID="20261025T231730Z-d7d67cc7"   # example from PR #670's record; use YOUR printed run ID
  make platform-evidence-validate ENV=lab TIER=docker \
    MANIFEST=".artifacts/platform/lab/$RUN_ID/manifest.json" \
    COMMIT="$(git rev-parse HEAD)"
  # VM host record (host-verify.v1; the run ID printed by platform-host-verify; see
  # inventory-and-host.md Part C):
  RUN_ID="20261026T101500Z-4c5d6e7f"   # example format; use YOUR printed run ID
  make platform-evidence-validate ENV=lab TIER=vm \
    MANIFEST=".artifacts/platform/$RUN_ID/manifest.json" \
    COMMIT="$(git rev-parse HEAD)"
  ```

  Expect `evidence-validation=pass scope=docker-lab-lifecycle` or `scope=host-baseline`, plus the tool's own scope reminder line. Anything incomplete, non-passing, mismatched with the commit, or from an unknown later schema exits 2 with `evidence-validation=fail: ...`; record that as a failed check, never as a pass.
- Attach sanitized manifests and command exit codes to the issue when working it, per [agent-execution.md](../agent-execution.md#required-issue-completion-evidence). Anything secret-bearing goes to your restricted evidence storage, referenced opaquely.

## Troubleshooting

Messages are quoted from the actual tools; fix the named prerequisite, never bypass the check.

| Symptom | Cause and fix |
|---|---|
| `PLATFORM_DOCKER_CONTEXT must explicitly select a local context` | Export `PLATFORM_DOCKER_CONTEXT` (Stage 2 step 3). |
| `the selected Docker context is not in PLATFORM_ALLOWED_DOCKER_CONTEXTS` | The allowlist must contain exactly the context you selected; set both variables in the same shell. |
| `ENV=lab requires an explicitly allowlisted local Docker endpoint` | The context's endpoint is not a local Unix/named-pipe socket; inspect `docker context inspect <name>` and pick the local one. |
| `production and non-lab Docker contexts are refused` | The context name matches the reserved pattern (`prod`, `legacy`, `rehearsal`, `hcloud`, `hetzner`, `remote`); choose or rename a neutral local context and allowlist that. |
| `the platform lab refuses Docker daemons with Swarm enabled or unknown` | Leave Swarm off on the lab daemon; do not run `docker swarm init`; pick another daemon if this one runs Swarm. |
| `the lab refuses production credentials in the process environment` | Unset the cloud credential variables listed in Stage 4 step 1 in that shell. |
| `pinned local tool versions are missing or mismatched: ...` | Re-activate the pins: open a new shell with pyenv initialized, recreate `.venv-platform` if it drifted, and check `.tools/platform` (Stage 3 installs). |
| `required project-local Ansible collections are missing or mismatched` | Re-run the `ansible-galaxy collection install` command from Stage 3 step 3. |
| `another platform lab lifecycle operation is active` | Another lab command holds `.artifacts/platform/lab/lifecycle.lock`; only one lifecycle operation per checkout at a time. |
| `run ID must use YYYYMMDDTHHMMSSZ-<8 lowercase hex characters>` or resume mismatch | Lab inputs changed since the recorded run; run `make platform-lab-down ENV=lab` then a fresh `up`. |
| `the platform Ansible command requires the pinned Python version` | `platform-ansible-test`/`platform-host-verify` run inside `.venv-platform` at the pinned version; recreate the venv if it drifted. |
| Molecule build fails to pull the base image | Check daemon connectivity and disk; the scenario image is built locally from `ansible/molecule/default/Dockerfile.j2` with `--network host`, so an offline build needs that network path. |
| `No rule for target "..."; unimplemented platform commands fail closed.` | The target (for example `platform-inventory`) is not implemented on this checkout; see [inventory-and-host.md](inventory-and-host.md) and do not fake it. |

## Where to go next

- [inventory-and-host.md](inventory-and-host.md): P0 live inventory reconciliation (#653) and the P1 host tier, including `make platform-host-verify ENV=lab TIER=vm` with a disposable Ubuntu 24.04 VM, signed SSH trust, Tailscale, and storage guards.
- [delivery.md](delivery.md): release bundle rendering, promotion and registry checks (P2/P3 work).
- [migration.md](migration.md): rehearsal, cutover, rollback and recovery (P4/P5/P6 work).
- [work-items.json](../work-items.json) remains the dependency graph; GitHub issues remain the live status.
