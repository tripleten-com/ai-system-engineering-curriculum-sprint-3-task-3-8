"""Coldline.

===================

File:              tests/contract/gitops_contract.py
Component:         Contract tests — GitOps helpers
Purpose:           Read the branch history, the reconciler's records, and the stack for the checks.
Interacts With:    git, deploy/desired-state.yaml, the reconciler, Docker, submission.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          GitOps, commit as the change, revert as the rollback, drift
Tools:             Python 3.12, git, Docker, Docker Compose

The checks never import the reconciler. They run it exactly as a student does, as a
subprocess, and read the JSON record it prints, so what they assert is what the record
shows, not an internal function's return value.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import yaml

TASK_ROOT = Path(__file__).resolve().parents[2]
DESIRED_STATE_PATH = "deploy/desired-state.yaml"
RECONCILER = TASK_ROOT / "infra/gitops/reconcile.py"
COMPOSE_PROFILES = ("--profile", "observability", "--profile", "localstack")
DESIRED_STATE_KEYS = (
    "release_tag",
    "api.restart_policy",
    "worker.restart_policy",
    "worker.replicas",
)
RESTART_POLICIES = ("no", "always", "on-failure", "unless-stopped")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
# The line `git revert` writes into every revert commit's message. A rollback made by
# editing the tag back and committing produces the same file contents but never this line.
REVERT_LINE = re.compile(r"This reverts commit ([0-9a-f]{40})")


class HistoryError(ValueError):
    """Report one actionable branch-history failure."""


def git(*args: str) -> str:
    """Run one git command in the Task root and return its trimmed output."""
    result = subprocess.run(
        ["git", *args], cwd=TASK_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise HistoryError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def commit_exists(sha: str) -> bool:
    """Return whether one full SHA names a commit this repository holds."""
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "commit"


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """Return whether ``ancestor`` is reachable from ``descendant``."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def commit_message(sha: str) -> str:
    """Return one commit's full message."""
    return git("log", "-1", "--format=%B", sha)


def desired_state_at(revision: str) -> dict[str, Any]:
    """Return the desired state committed at one revision, as its four dotted keys."""
    try:
        text = git("show", f"{revision}:{DESIRED_STATE_PATH}")
    except HistoryError as exc:
        raise HistoryError(f"{DESIRED_STATE_PATH} is not committed at {revision}") from exc
    document = yaml.safe_load(text)
    if not isinstance(document, dict):
        raise HistoryError(f"{DESIRED_STATE_PATH} at {revision} is not one YAML mapping")
    raw_api, raw_worker = document.get("api"), document.get("worker")
    api: dict[str, Any] = raw_api if isinstance(raw_api, dict) else {}
    worker: dict[str, Any] = raw_worker if isinstance(raw_worker, dict) else {}
    return {
        "release_tag": document.get("release_tag"),
        "api.restart_policy": _policy(api.get("restart_policy")),
        "worker.restart_policy": _policy(worker.get("restart_policy")),
        "worker.replicas": worker.get("replicas"),
    }


def _policy(value: object) -> object:
    """Normalize a restart policy; YAML reads a bare `no` as the boolean false."""
    return "no" if value is False else value


def load_answers() -> dict[str, Any]:
    """Load the recorded answers; a blank sheet still lets the runtime checks run."""
    document = yaml.safe_load((TASK_ROOT / "submission.yaml").read_text(encoding="utf-8"))
    recorded = document.get("answers") if isinstance(document, dict) else None
    return recorded if isinstance(recorded, dict) else {}


def load_manifest() -> dict[str, Any]:
    """Return the supplied release manifest."""
    return cast(
        dict[str, Any],
        yaml.safe_load((TASK_ROOT / "infra/release/manifest.yaml").read_text(encoding="utf-8")),
    )


def manifest_tags(manifest: dict[str, Any]) -> dict[str, str]:
    """Return every manifest tag mapped to the build version it stamps."""
    return {
        str(release["tag"]): str(release["build_version"])
        for release in manifest["releases"].values()
    }


def run_reconciler(command: str) -> dict[str, Any]:
    """Run `check` or `apply` exactly as `poe` does and return the JSON record it printed."""
    result = subprocess.run(
        [sys.executable, str(RECONCILER), command],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HistoryError(f"reconcile.py {command} failed:\n{result.stderr.strip()}")
    return cast(dict[str, Any], json.loads(result.stdout))


def compose_records() -> list[dict[str, Any]]:
    """Return every Compose container record for this project, running or not."""
    result = subprocess.run(
        ["docker", "compose", *COMPOSE_PROFILES, "ps", "--all", "--format", "json"],
        cwd=TASK_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HistoryError(f"docker compose ps failed: {result.stderr.strip()}")
    text = result.stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        return cast(list[dict[str, Any]], json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def restart_policy(container_name: str) -> str:
    """Return the restart policy Docker reports for one container, as `docker inspect` does."""
    result = subprocess.run(
        ["docker", "inspect", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise HistoryError(f"docker inspect failed for {container_name}: {result.stderr}")
    details = json.loads(result.stdout)[0]
    return str(details.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") or "no")
