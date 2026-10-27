# Agent execution contract

## Goal

Implement the core AniTrend private platform roadmap from P0-01 through P6-01 using the linked GitHub issues and repository docs. A fresh reader must be able to understand the baseline, build the local Docker lab, validate infrastructure/host configuration, rehearse on Hetzner and reach a controlled migration with recoverable data. P7-01 is optional follow-up.

Read AGENTS.md, this plan's README, ADR, current-state snapshot, validation contract and migration runbook before editing. Follow applicable project skills for changes under their owned paths. Do not overwrite existing agent guidance; keep it short and link canonical docs.

## Work selection and continuation

Use work-items.json for the dependency graph and issue URLs. Query GitHub for current issue/PR state and read prerequisite completion evidence. Never assume an issue is implemented just because it is closed. Start only work whose prerequisites are complete, except that independent P0 discovery and P1 lab work can proceed separately. The documentation PR is a versioned starting point, not an additional permission checkpoint for authorized implementation.

Explicitly authorized development may build on unmerged prerequisite PRs with synthetic inputs while VM or cloud access is unavailable. Record the stack base and the deferred acceptance in the PR and [operator handoff](runbooks/README.md). This does not satisfy an operational gate, authorize cloud spend, or waive required reviews. Keep the full migration goal and its remaining acceptance criteria open.

Use an isolated branch/worktree for each coherent implementation change. Refresh dev and record its SHA. Compare newer source with the immutable planning baseline; update affected assumptions through review. Do not reset or overwrite unrelated user/agent changes.

For each issue: state the candidate goal and relevant gate; implement the owned scope; run the specified meaningful assertions; update canonical docs and environment schemas; submit a focused PR linking the issue and evidence. Preserve current runtime until its explicit ownership handoff. Do not merge or promote outside existing authorization/repository policy.

Resume from recorded state after interruption. Inventory current resources and release IDs before retrying any mutation. Reconciliation must not create duplicate resources or redeploy a stale release. Serialize mutations to the same environment.

## Required issue completion evidence

Attach a sanitized report containing:

- Implemented paths, PR and final tested commit.
- Exact commands, target environment/tier and exit results.
- Actual tool/provider/image versions, digests and CPU architecture.
- Assertions passed, failed, blocked or skipped, with reasons.
- Pulumi no-op/update/cleanup and Ansible convergence evidence where relevant.
- Deployment identity/readiness, network boundary and data restore proof where relevant.
- Rollback/recovery exercise and current ownership.
- Residual risks/resources, cost/expiry if retained, and follow-up issue links.

Do not publish secret values, raw inspect/environment exports, private keys or backup data. Evidence must be accessible to an authorized next implementer, not only in one agent's temporary workspace.

A PR description states the problem, resulting behaviour and validation. Mark the issue complete only when acceptance is satisfied and implementation is available on the integration branch under repository policy. Documentation-only changes cannot close runtime-validation issues.

## Boundaries and autonomy

Perform authorized code changes, local tests, read-only investigation and preparation without repeated confirmation. If credentials or a production decision are unavailable, report the exact missing input and continue independent offline work. Never fabricate it or mark an affected gate passed.

Creating the roadmap does not authorize paid provisioning, live traffic changes or data deletion. For later execution, respect explicit session authorization and configured repository environment protection. Before asking for a missing approval, produce the concrete preview, expected impact, applicable passing evidence and rollback plan. Routine implementation choices use the documented defaults.

Never use production secrets/data/hosts in the local lab. Do not alter the user's Docker context, initialize their daemon into Swarm, prune unrelated resources, disable SSH verification, expose admin ports or reformat populated volumes as a workaround.

## Stop conditions

Stop only the affected mutation when target identity is ambiguous; an actual image/data version contradicts the plan; required tests fail or are skipped; a secret appears in output; a delete/replacement falls outside scope; two controllers own the same service; a source/target writer cannot be fenced; or recovery evidence is invalid. Preserve evidence and explain the precise blocker.

An unavailable API or daemon is an environment blocker, not a pass. The planning session's Docker socket denial is one such observation, not a permanent assumption about the user's machine.

## Suggested harness goal

> Complete the core linked AniTrend platform issues in dependency order. Treat docs/platform as the design and execution contract and service folders as authored configuration. Establish real local Docker validation first, preserve the live environment while implementing, then produce and execute only the authorized disposable rehearsal and production stages. Require versioned evidence for every gate, one deployment owner per service, private administrative access and tested data recovery. Continue independent work when an external prerequisite is missing, and surface only concrete blockers or missing final authorization. Do not introduce Kubernetes or replace APISIX as part of the core goal.

## Initial publication status

This plan has been checked for source consistency, dependencies and cross-links. No implementation work item has passed runtime acceptance at publication. Docker CLI/context were detected, but the current session could not reach the daemon; Pulumi and Ansible were not found on PATH. P1 establishes the executable local environment.
