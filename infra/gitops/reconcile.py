"""Coldline.

===================

File:              infra/gitops/reconcile.py
Component:         GitOps tools — Reconciler
Purpose:           Make the running Compose stack match the desired state committed at HEAD.
Interacts With:    deploy/desired-state.yaml at HEAD, compose.yaml, the manifest, git, Docker
Sprint/Task:       Sprint 3 — Project 3
Concepts:          GitOps, desired state, drift detection, reconciliation, health-gated rollout
Tools:             Python 3.12, git, Docker, Docker Compose, httpx

The tool is supplied and protected. It reads the desired state from the latest commit on
your branch, never from your working tree, compares it with the running Compose services,
and prints a record of what it read, what differed, what it changed, and what was running
afterwards. Three things it deliberately does not do: it never builds during a reconcile
pass (`--no-build`), it never edits `compose.yaml` or `deploy/desired-state.yaml`, and it
never reconciles in the other direction (the commit is the source of truth, not the stack).

Commands:

    python infra/gitops/reconcile.py build   # build both manifest releases for api and worker
    python infra/gitops/reconcile.py check   # compare HEAD with the stack; change nothing
    python infra/gitops/reconcile.py apply   # one reconcile pass, then the record

The record is JSON on standard output; a one-line summary goes to standard error. The exit
code is non-zero only for a real failure (unreadable HEAD, an unknown tag, a Compose error),
never merely because drift was found.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

TASK_ROOT = Path(__file__).resolve().parents[2]
DESIRED_STATE_PATH = "deploy/desired-state.yaml"
# Generated on every reconcile pass that changes something, and git-ignored. It carries the
# two restart policies, which Compose can only take from a file, unlike the tag (an
# environment variable) and the replica count (`--scale`).
OVERRIDE_PATH = "deploy/.reconcile-override.yaml"
MANIFEST_PATH = TASK_ROOT / "infra/release/manifest.yaml"
COMPOSE_PROFILES = ("--profile", "observability", "--profile", "localstack")
TAG_VARIABLE = "COLDLINE_RELEASE_TAG"
# The services whose image tag the desired state governs. The initializer runs the api
# image and is recreated by Compose whenever api or worker depend on a new tag.
RELEASE_SERVICES = ("api", "initializer", "worker")
# The services whose restart policy the desired state governs.
POLICY_SERVICES = ("api", "worker")
RESTART_POLICIES = ("no", "always", "on-failure", "unless-stopped")
DESIRED_KEYS = ("release_tag", "api.restart_policy", "worker.restart_policy", "worker.replicas")


class ReconcileError(RuntimeError):
    """Report one actionable reconciler failure without a stack trace."""


# --- the desired state, read from git HEAD ---------------------------------------------


def git(*args: str) -> str:
    """Run one git command in the Task root and return its trimmed output."""
    result = subprocess.run(
        ["git", *args], cwd=TASK_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no detail"
        raise ReconcileError(f"git {args[0]} failed: {detail}")
    return result.stdout.strip()


def read_head() -> tuple[str, dict[str, Any]]:
    """Return HEAD's commit SHA and the desired state committed there."""
    commit = git("rev-parse", "HEAD")
    try:
        text = git("show", f"HEAD:{DESIRED_STATE_PATH}")
    except ReconcileError as exc:
        raise ReconcileError(
            f"{DESIRED_STATE_PATH} is not committed at HEAD ({exc}); the reconciler reads "
            "the desired state from the latest commit, not from the working tree"
        ) from exc
    return commit, parse_desired_state(text)


def parse_desired_state(text: str) -> dict[str, Any]:
    """Validate the desired-state document and return it with normalized values."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ReconcileError(f"{DESIRED_STATE_PATH} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"release_tag", "api", "worker"}:
        raise ReconcileError(
            f"{DESIRED_STATE_PATH} must declare exactly release_tag, api, and worker"
        )
    tag = document["release_tag"]
    if not isinstance(tag, str) or not tag.strip():
        raise ReconcileError("release_tag must be a non-empty string")
    api = document["api"]
    if not isinstance(api, dict) or set(api) != {"restart_policy"}:
        raise ReconcileError("api must declare exactly restart_policy")
    worker = document["worker"]
    if not isinstance(worker, dict) or set(worker) != {"restart_policy", "replicas"}:
        raise ReconcileError("worker must declare exactly restart_policy and replicas")
    replicas = worker["replicas"]
    if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 1:
        raise ReconcileError("worker.replicas must be a whole number of at least 1")
    return {
        "release_tag": tag,
        "api": {"restart_policy": _policy(api["restart_policy"], "api")},
        "worker": {
            "restart_policy": _policy(worker["restart_policy"], "worker"),
            "replicas": replicas,
        },
    }


def _policy(value: object, service: str) -> str:
    """Normalize one restart policy; a bare YAML `no` arrives as the boolean false."""
    if value is False:
        value = "no"
    if not isinstance(value, str) or value not in RESTART_POLICIES:
        raise ReconcileError(
            f"{service}.restart_policy must be one of {', '.join(RESTART_POLICIES)}"
        )
    return value


def flatten(desired: dict[str, Any]) -> dict[str, Any]:
    """Return the desired state as the four dotted keys the record and the checks use."""
    return {
        "release_tag": desired["release_tag"],
        "api.restart_policy": desired["api"]["restart_policy"],
        "worker.restart_policy": desired["worker"]["restart_policy"],
        "worker.replicas": desired["worker"]["replicas"],
    }


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Return the supplied release manifest as one mapping."""
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or "releases" not in manifest or "images" not in manifest:
        raise ReconcileError("infra/release/manifest.yaml does not declare images and releases")
    return cast(dict[str, Any], manifest)


def manifest_tags(manifest: dict[str, Any]) -> dict[str, str]:
    """Return every manifest tag mapped to the build version it stamps."""
    return {
        str(release["tag"]): str(release["build_version"])
        for release in manifest["releases"].values()
    }


# --- the observed state, read from Docker ----------------------------------------------


def compose(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run one Docker Compose command in the Task root with the supplied profiles."""
    return subprocess.run(
        ["docker", "compose", *COMPOSE_PROFILES, *args],
        cwd=TASK_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def compose_records() -> list[dict[str, Any]]:
    """Return every Compose container record for this project, running or not."""
    result = compose("ps", "--all", "--format", "json")
    if result.returncode != 0:
        raise ReconcileError(f"docker compose ps failed: {result.stderr.strip()}")
    text = result.stdout.strip()
    if not text:
        return []
    # Compose v2.21+ prints one JSON object per line; earlier releases print one array.
    if text.startswith("["):
        return cast(list[dict[str, Any]], json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def restart_policies(container_names: list[str]) -> list[str]:
    """Return the restart policy Docker applied to each named container."""
    if not container_names:
        return []
    inspected = subprocess.run(
        ["docker", "inspect", *container_names],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspected.returncode != 0:
        raise ReconcileError(f"docker inspect failed: {inspected.stderr.strip()}")
    policies = []
    for details in json.loads(inspected.stdout):
        name = details.get("HostConfig", {}).get("RestartPolicy", {}).get("Name") or "no"
        policies.append(str(name))
    return policies


def observe() -> dict[str, Any]:
    """Read the running stack: image tag per service, restart policies, worker replicas."""
    records = compose_records()
    by_service: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_service.setdefault(str(record.get("Service")), []).append(record)
    tags: dict[str, list[str]] = {}
    for service in RELEASE_SERVICES:
        images = {
            str(entry.get("Image", "")).rsplit(":", maxsplit=1)[-1]
            for entry in by_service.get(service, [])
        }
        tags[service] = sorted(images)
    policies: dict[str, list[str]] = {}
    for service in POLICY_SERVICES:
        names = [str(entry["Name"]) for entry in by_service.get(service, [])]
        policies[service] = sorted(set(restart_policies(names)))
    return {
        "release_tag": tags,
        "api": {"restart_policy": policies["api"]},
        "worker": {
            "restart_policy": policies["worker"],
            "replicas": len(by_service.get("worker", [])),
        },
    }


def _render_tags(per_service: dict[str, list[str]]) -> str:
    """Render the observed tags: one value when every service agrees, else per service."""
    distinct = {tuple(tags) for tags in per_service.values()}
    if len(distinct) == 1:
        return _render_values(next(iter(distinct)))
    return ", ".join(
        f"{service}={_render_values(per_service[service])}" for service in RELEASE_SERVICES
    )


def _render_values(values: tuple[str, ...] | list[str]) -> str:
    """Render one observed value list: the value, `absent`, or the disagreeing set."""
    if not values:
        return "absent"
    return ", ".join(values)


def flatten_observed(observed: dict[str, Any]) -> dict[str, Any]:
    """Return the observed state under the same dotted keys as the desired state."""
    return {
        "release_tag": _render_tags(observed["release_tag"]),
        "api.restart_policy": _render_values(observed["api"]["restart_policy"]),
        "worker.restart_policy": _render_values(observed["worker"]["restart_policy"]),
        "worker.replicas": observed["worker"]["replicas"],
    }


def differences(desired: dict[str, Any], observed: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every dotted key whose observed value differs from the committed one."""
    found: list[dict[str, Any]] = []
    tag = desired["release_tag"]
    if any(tags != [tag] for tags in observed["release_tag"].values()):
        found.append(
            {
                "key": "release_tag",
                "desired": tag,
                "observed": _render_tags(observed["release_tag"]),
            }
        )
    for service in POLICY_SERVICES:
        wanted = desired[service]["restart_policy"]
        seen = observed[service]["restart_policy"]
        if seen != [wanted]:
            found.append(
                {
                    "key": f"{service}.restart_policy",
                    "desired": wanted,
                    "observed": _render_values(seen),
                }
            )
    if observed["worker"]["replicas"] != desired["worker"]["replicas"]:
        found.append(
            {
                "key": "worker.replicas",
                "desired": desired["worker"]["replicas"],
                "observed": observed["worker"]["replicas"],
            }
        )
    return found


# --- the API probe, behind the readiness gate --------------------------------------------


def _host_port() -> int:
    """Return the API host port from the shell, the local `.env`, or the default 8000."""
    value = os.environ.get("COLDLINE_API_HOST_PORT")
    dotenv = TASK_ROOT / ".env"
    if value is None and dotenv.is_file():
        for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("COLDLINE_API_HOST_PORT="):
                value = line.split("=", maxsplit=1)[1].strip().strip('"').strip("'")
    if value is None:
        return 8000
    try:
        port = int(value)
    except ValueError as exc:
        raise ReconcileError("COLDLINE_API_HOST_PORT must be an integer host port") from exc
    if not 1 <= port <= 65_535:
        raise ReconcileError("COLDLINE_API_HOST_PORT must be between 1 and 65535")
    return port


def probe() -> dict[str, Any]:
    """Return what one request sees right now: readiness status and the build that answered."""
    with httpx.Client(base_url=f"http://localhost:{_host_port()}", timeout=5.0) as client:
        try:
            ready = client.get("/health/ready")
            ready_status: int | None = ready.status_code
        except httpx.HTTPError:
            ready_status = None
        try:
            version = client.get("/version")
            reported = version.json().get("build_version") if version.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            reported = None
    return {"ready_status": ready_status, "build_version": reported}


# --- the three commands --------------------------------------------------------------------


def build(manifest: dict[str, Any] | None = None) -> list[str]:
    """Build every manifest release for both first-party images; return the tags built."""
    manifest = load_manifest() if manifest is None else manifest
    built: list[str] = []
    for name, dockerfile in (
        ("api", "infra/containers/api.Dockerfile"),
        ("worker", "infra/containers/worker.Dockerfile"),
    ):
        image = str(manifest["images"][name])
        for release in manifest["releases"].values():
            reference = f"{image}:{release['tag']}"
            arguments = [
                "docker",
                "build",
                "--file",
                dockerfile,
                "--tag",
                reference,
                "--build-arg",
                f"COLDLINE_BUILD_VERSION={release['build_version']}",
            ]
            if name == "api":
                arguments += [
                    "--build-arg",
                    f"COLDLINE_READY_DELAY_SECONDS={release['ready_delay_seconds']}",
                ]
            arguments.append(".")
            result = subprocess.run(arguments, cwd=TASK_ROOT, check=False)
            if result.returncode != 0:
                raise ReconcileError(f"docker build failed for {reference}")
            built.append(reference)
    return built


def check() -> dict[str, Any]:
    """Compare HEAD's desired state with the running stack and change nothing."""
    commit, desired = read_head()
    observed = observe()
    found = differences(desired, observed)
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "check",
        "commit": commit,
        "desired": flatten(desired),
        "observed": flatten_observed(observed),
        "differences": found,
        "drift": bool(found),
        "probe": probe(),
    }


def write_override(desired: dict[str, Any], commit: str) -> Path:
    """Write the generated Compose override that carries the two restart policies."""
    path = TASK_ROOT / OVERRIDE_PATH
    lines = [
        "# Coldline - Task 3.8",
        f"# Generated by infra/gitops/reconcile.py from {DESIRED_STATE_PATH} at commit {commit}.",
        "# Git-ignored. Never edit or commit it; change deploy/desired-state.yaml instead.",
        "services:",
    ]
    for service in POLICY_SERVICES:
        lines.append(f"  {service}:")
        # json.dumps quotes the value, which keeps a policy of `no` a string for Compose.
        lines.append(f"    restart: {json.dumps(desired[service]['restart_policy'])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _describe(found: list[dict[str, Any]], desired: dict[str, Any]) -> list[str]:
    """Say, per difference, what the single Compose pass below will do about it."""
    actions = []
    for difference in found:
        key = str(difference["key"])
        if key == "release_tag":
            actions.append(
                f"release_tag: set {TAG_VARIABLE}={desired['release_tag']} and recreate api "
                f"and worker (and the initializer they depend on) from the "
                f"{desired['release_tag']} images"
            )
        elif key.endswith(".restart_policy"):
            service = key.split(".", maxsplit=1)[0]
            actions.append(
                f"{key}: write restart {desired[service]['restart_policy']} into "
                f"{OVERRIDE_PATH} and recreate {service} with it"
            )
        else:
            actions.append(
                f"worker.replicas: scale worker to {desired['worker']['replicas']} "
                f"(--scale worker={desired['worker']['replicas']})"
            )
    return actions


def apply() -> dict[str, Any]:
    """Run one reconcile pass: read HEAD, apply every difference, record the result."""
    commit, desired = read_head()
    tags = manifest_tags(load_manifest())
    if desired["release_tag"] not in tags:
        raise ReconcileError(
            f"release_tag {desired['release_tag']!r} at HEAD is not a manifest release; "
            f"the manifest names {', '.join(sorted(tags))}"
        )
    observed = observe()
    found = differences(desired, observed)
    actions: list[str] = []
    waited = 0.0
    if found:
        actions = _describe(found, desired)
        write_override(desired, commit)
        environment = os.environ.copy()
        environment[TAG_VARIABLE] = desired["release_tag"]
        command = [
            "-f",
            "compose.yaml",
            "-f",
            OVERRIDE_PATH,
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--scale",
            f"worker={desired['worker']['replicas']}",
            *POLICY_SERVICES,
        ]
        actions.append(
            f"{TAG_VARIABLE}={desired['release_tag']} docker compose "
            + " ".join((*COMPOSE_PROFILES, *command))
        )
        started = time.monotonic()
        up = compose(*command, env=environment)
        waited = round(time.monotonic() - started, 1)
        if up.returncode != 0:
            detail = up.stderr.strip().splitlines()[-1] if up.stderr.strip() else "no detail"
            raise ReconcileError(
                f"docker compose up --no-build --wait failed while reconciling to {commit[:12]}: "
                f"{detail} (run `poe release-build` first if an image is missing)"
            )
    first = probe()
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": "reconcile",
        "commit": commit,
        "desired": flatten(desired),
        "differences": found,
        "actions": actions,
        "compose_wait_seconds": waited,
        "first_probe": first,
        "observed": flatten_observed(observe()),
    }


def main(argv: list[str] | None = None) -> int:
    """Run one command from the command line and print its JSON record."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="build every manifest release for both images")
    commands.add_parser("check", help="compare HEAD with the running stack; change nothing")
    commands.add_parser("apply", help="one reconcile pass from HEAD, then the record")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            record: dict[str, Any] = {"built": build()}
            summary = f"built {len(record['built'])} image references"
        elif args.command == "check":
            record = check()
            count = len(record["differences"])
            summary = (
                f"commit {record['commit'][:12]}: no drift"
                if not count
                else f"commit {record['commit'][:12]}: drift on {count} key(s): "
                + ", ".join(str(item["key"]) for item in record["differences"])
            )
        else:
            record = apply()
            count = len(record["differences"])
            summary = (
                f"commit {record['commit'][:12]}: nothing to change"
                if not count
                else f"commit {record['commit'][:12]}: applied {count} difference(s) in "
                f"{record['compose_wait_seconds']} s"
            )
    except ReconcileError as exc:
        print(f"reconcile failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=2, sort_keys=True))
    print(summary, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
