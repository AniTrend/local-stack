from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap



REPO_ROOT = Path(__file__).resolve().parents[2]
PREVIEW_CLI = REPO_ROOT / "tools" / "platform" / "pulumi_preview.py"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def fake_pulumi_environment(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "infra" / "pulumi" / "hcloud"
    project_dir.mkdir(parents=True)
    (project_dir / "node_modules" / "@pulumi" / "hcloud").mkdir(parents=True)
    (project_dir / "Pulumi.yaml").write_text("name: fixture\n", encoding="utf-8")
    version_file = repo_root / "tools" / "platform" / "pulumi-version.txt"
    version_file.parent.mkdir(parents=True)
    version_file.write_text("3.272.0\n", encoding="utf-8")

    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    command_log = tmp_path / "pulumi-commands.log"
    write_executable(
        binary_dir / "pulumi",
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s|%s\\n' "$PWD" "$*" >> "$PLATFORM_TEST_PULUMI_LOG"
            if [ "$1" = "version" ]; then printf 'v3.272.0\\n'; exit 0; fi
            if [ "$1" = "whoami" ]; then printf 'User: fixture\\nBackend URL: %s\\n' "${PLATFORM_TEST_PULUMI_BACKEND:-https://app.pulumi.com/fixture}"; exit 0; fi
            if [ "$*" = "preview --diff --non-interactive --stack production" ]; then exit 0; fi
            exit 64
            """
        ),
    )
    environment = os.environ.copy()
    environment["PATH"] = str(binary_dir) + os.pathsep + environment.get("PATH", "")
    environment["PLATFORM_PULUMI_BIN"] = "pulumi"
    environment["PLATFORM_TEST_PULUMI_LOG"] = str(command_log)
    return repo_root, environment


def test_production_preview_uses_pinned_cli_and_only_runs_diff_preview(tmp_path: Path):
    repo_root, environment = fake_pulumi_environment(tmp_path)

    result = subprocess.run(
        [sys.executable, str(PREVIEW_CLI), "--environment", "production", "--repo-root", str(repo_root)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = environment["PLATFORM_TEST_PULUMI_LOG"]
    recorded = Path(commands).read_text(encoding="utf-8").splitlines()
    project_dir = repo_root / "infra" / "pulumi" / "hcloud"
    assert recorded == [
        f"{repo_root}|version",
        f"{project_dir}|whoami --verbose --non-interactive --color=never",
        f"{project_dir}|preview --diff --non-interactive --stack production",
    ]


def test_invalid_preview_environment_fails_before_invoking_pulumi(tmp_path: Path):
    repo_root, environment = fake_pulumi_environment(tmp_path)

    result = subprocess.run(
        [sys.executable, str(PREVIEW_CLI), "--environment", "legacy", "--repo-root", str(repo_root)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode != 0
    assert not Path(environment["PLATFORM_TEST_PULUMI_LOG"]).exists()

def test_production_preview_rejects_non_cloud_state_backend(tmp_path: Path):
    repo_root, environment = fake_pulumi_environment(tmp_path)
    environment["PLATFORM_TEST_PULUMI_BACKEND"] = "file:///tmp/local-state"

    result = subprocess.run(
        [sys.executable, str(PREVIEW_CLI), "--environment", "production", "--repo-root", str(repo_root)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )

    assert result.returncode == 2
    assert "Pulumi Cloud state backend" in result.stderr
    recorded = Path(environment["PLATFORM_TEST_PULUMI_LOG"]).read_text(encoding="utf-8").splitlines()
    assert len(recorded) == 2
    assert recorded[-1].endswith("|whoami --verbose --non-interactive --color=never")
