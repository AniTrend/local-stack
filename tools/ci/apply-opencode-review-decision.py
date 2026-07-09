#!/usr/bin/env python3
"""Apply PR review decision based on OpenCode risk assessment."""

import json
import os
import subprocess
import sys

# Unique header used to identify the bot's own neutral-decision comment for in-place updates.
COMMENT_MARKER = "OpenCode risk gate"


def find_existing_comment_id(env: dict, repo: str, pr_number: str, marker: str) -> str | None:
    """Return the node_id of the first PR comment containing `marker`, or None."""
    result = subprocess.run(
        [
            "gh", "api",
            f"repos/{repo}/issues/{pr_number}/comments",
            "--jq",
            f'[.[] | select(.body | contains("{marker}"))][0].id',
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    comment_id = result.stdout.strip()
    if result.returncode == 0 and comment_id and comment_id != "null":
        return comment_id
    return None


def upsert_pr_comment(env: dict, repo: str, pr_number: str, body: str, marker: str) -> str:
    """Update existing bot comment if it exists, otherwise create a new one.

    Returns "updated" or "created".
    """
    existing_id = find_existing_comment_id(env, repo, pr_number, marker)
    if existing_id:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(body)
            tmp_path = f.name
        try:
            subprocess.run(
                [
                    "gh", "api",
                    "-X", "PATCH",
                    f"repos/{repo}/issues/comments/{existing_id}",
                    "--input", tmp_path,
                ],
                env=env,
                check=True,
            )
        finally:
            os.unlink(tmp_path)
        return "updated"
    else:
        subprocess.run(
            ["gh", "pr", "comment", pr_number, "--repo", repo, "--body", body],
            env=env,
            check=True,
        )
        return "created"


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
        action = upsert_pr_comment(env, repo, pr_number, body, COMMENT_MARKER)
        print(f"Neutral-decision comment {action} on PR #{pr_number}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: apply-opencode-review-decision.py <output-file> <gh-token> <repo> <pr-number>", file=sys.stderr)
        sys.exit(2)
    sys.exit(apply_decision(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
