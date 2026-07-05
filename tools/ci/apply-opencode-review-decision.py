#!/usr/bin/env python3
"""Apply PR review decision based on OpenCode risk assessment."""

import json
import os
import subprocess
import sys


def apply_decision(output_file: str, gh_token: str, repo: str, pr_number: str) -> int:
    with open(output_file) as f:
        data = json.load(f)

    decision = data.get("decision", "neutral")
    automerge_allowed = data.get("automerge_allowed", False)
    env = {**os.environ, "GH_TOKEN": gh_token}

    if decision == "approve":
        print(f"Approving PR #{pr_number}...")
        body = (
            "OpenCode risk gate: low risk detected. "
            f"Update type: {data.get('update_type', 'unknown')}. "
            f"Ecosystem: {data.get('dependency_ecosystem', 'unknown')}."
        )
        subprocess.run(
            ["gh", "pr", "review", pr_number, "--repo", repo, "--approve", "--body", body],
            env=env,
            check=True,
        )

        if automerge_allowed:
            print(f"Enabling auto-merge for PR #{pr_number}...")
            subprocess.run(
                ["gh", "pr", "merge", pr_number, "--repo", repo, "--auto", "--rebase"],
                env=env,
                check=False,  # Non-fatal: auto-merge may not be available yet
            )

    elif decision == "changes_requested":
        print(f"Requesting changes on PR #{pr_number}...")
        body = (
            "OpenCode risk gate: changes requested. "
            f"Risk: {data.get('risk', 'unknown')}. "
            f"Reason: {data.get('summary', 'No reason provided.')}"
        )
        subprocess.run(
            ["gh", "pr", "review", pr_number, "--repo", repo, "--request-changes", "--body", body],
            env=env,
            check=True,
        )

    else:
        print(f"Neutral decision for PR #{pr_number}. No action taken.")
        body = (
            "OpenCode risk gate: neutral. Manual review required. "
            f"Risk: {data.get('risk', 'unknown')}. "
            f"Reason: {data.get('summary', 'No reason provided.')}"
        )
        subprocess.run(
            ["gh", "pr", "comment", pr_number, "--repo", repo, "--body", body],
            env=env,
            check=True,
        )

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: apply-opencode-review-decision.py <output-file> <gh-token> <repo> <pr-number>", file=sys.stderr)
        sys.exit(2)
    sys.exit(apply_decision(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
