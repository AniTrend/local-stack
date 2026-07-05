#!/usr/bin/env python3
"""Post a deterministic PR comment with the OpenCode risk review result."""

import json
import os
import subprocess
import sys


def format_comment(data: dict) -> str:
    decision = data["decision"].upper()
    risk = data["risk"].upper()
    automerge = str(data.get("automerge_allowed", False)).lower()
    ecosystem = data.get("dependency_ecosystem", "unknown")
    update_type = data.get("update_type", "unknown")
    summary = data.get("summary", "No summary provided.")
    runtime_impact = data.get("runtime_impact", "Unknown")
    breaking = data.get("breaking_change_assessment", "Not assessed")
    required_checks = data.get("required_checks", [])
    manual_follow_up = data.get("manual_follow_up", [])
    sources = data.get("sources_checked", [])
    changed_images = data.get("changed_images", [])

    comment = f"""## OpenCode Dependabot Risk Review

Schema: `local-stack.dependabot-risk.v1`

Decision: `{decision}`
Risk: `{risk}`
Automerge allowed: `{automerge}`
Update type: `{update_type}`
Ecosystem: `{ecosystem}`

### Summary

{summary}

### Changed runtime artifacts

"""

    if changed_images:
        comment += "| Image / dependency | From | To | Risk note |\n"
        comment += "|---|---|---|---|\n"
        for img in changed_images:
            name = img.get("name", "?")
            frm = img.get("from", "?")
            to = img.get("to", "?")
            note = img.get("risk_reason", "-")
            comment += f"| `{name}` | `{frm}` | `{to}` | {note} |\n"
    else:
        comment += "No runtime image changes detected.\n"

    comment += f"""
### Runtime impact

{runtime_impact}

### Breaking change assessment

{breaking}

### Required checks

"""
    for check in required_checks:
        comment += f"- [ ] `{check}`\n"

    comment += "\n### Manual follow-up\n\n"
    if manual_follow_up:
        for item in manual_follow_up:
            comment += f"- {item}\n"
    else:
        comment += "None\n"

    comment += "\n### Sources checked\n\n"
    for source in sources:
        comment += f"- {source}\n"

    return comment


def main(output_file: str, gh_token: str, repo: str, pr_number: str) -> int:
    with open(output_file) as f:
        data = json.load(f)

    comment = format_comment(data)

    # Write to temp file to avoid shell escaping issues
    comment_file = ".review/comment-body.md"
    with open(comment_file, "w") as f:
        f.write(comment)

    env = {**os.environ, "GH_TOKEN": gh_token}
    subprocess.run(
        ["gh", "pr", "comment", pr_number, "--repo", repo, "--body-file", comment_file],
        env=env,
        check=True,
    )

    print(f"Comment posted to PR #{pr_number}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: comment-opencode-risk-review.py <output-file> <gh-token> <repo> <pr-number>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
