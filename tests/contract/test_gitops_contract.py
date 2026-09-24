"""Coldline.

===================

File:              tests/contract/test_gitops_contract.py
Component:         Contract tests — GitOps
Purpose:           Check the branch history, the recorded answers, and one reconcile pass at HEAD.
Interacts With:    git, deploy/desired-state.yaml, the reconciler, the stack, submission.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          GitOps, commit as the change, revert as the rollback, drift, reconciliation
Tools:             Python 3.12, pytest, git, Docker Compose

Every check here reads the branch, the committed desired state, the answer sheet, or the
running stack. None of them reads the GitOps record: the record is the defense material,
and these are the behavior your branch and your stack have to show on their own. The
history checks need git but no Docker; the two checks marked `runtime` reconcile the stack
to HEAD and read it back.
"""

from typing import Any

import pytest

from tests.contract import gitops_contract as history

pytestmark = [pytest.mark.assessed]


@pytest.fixture(scope="module")
def answers() -> dict[str, Any]:
    """Load the recorded answers once."""
    return history.load_answers()


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    """Load the supplied release manifest once."""
    return history.load_manifest()


@pytest.fixture(scope="module")
def head_state() -> dict[str, Any]:
    """Read the desired state committed at HEAD once."""
    return history.desired_state_at("HEAD")


def test_desired_state_at_head_keeps_the_supplied_keys_and_names_a_manifest_tag(
    head_state: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """HEAD's desired state keeps release_tag, api, and worker, with legal values."""
    tags = history.manifest_tags(manifest)
    assert head_state["release_tag"] in tags, (
        f"release_tag at HEAD must name a manifest release ({', '.join(sorted(tags))}); "
        f"got {head_state['release_tag']!r}"
    )
    for key in ("api.restart_policy", "worker.restart_policy"):
        assert head_state[key] in history.RESTART_POLICIES, (
            f"{key} at HEAD must be one of {', '.join(history.RESTART_POLICIES)}; "
            f"got {head_state[key]!r}"
        )
    replicas = head_state["worker.replicas"]
    assert isinstance(replicas, int) and not isinstance(replicas, bool) and replicas >= 1, (
        f"worker.replicas at HEAD must be a whole number of at least 1; got {replicas!r}"
    )


def test_rollout_and_rollback_commits_are_distinct_full_shas_on_this_branch(
    answers: dict[str, Any],
) -> None:
    """Both recorded commits are full 40-character SHAs reachable from HEAD, and differ."""
    rollout = answers.get("rollout_commit")
    rollback = answers.get("rollback_commit")
    for name, value in (("rollout_commit", rollout), ("rollback_commit", rollback)):
        assert isinstance(value, str) and history.FULL_SHA.match(value), (
            f"answers.{name} must be the full 40-character SHA from git rev-parse HEAD"
        )
        assert history.commit_exists(value), f"answers.{name} names no commit in this repository"
        assert history.is_ancestor(value, "HEAD"), f"answers.{name} is not on this branch"
    assert rollout != rollback, "the rollout and the rollback are two different commits"


def test_rollout_commit_changes_the_release_tag_to_the_candidate(
    answers: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The rollout commit moves release_tag from the known-good tag to the candidate only."""
    rollout = answers.get("rollout_commit")
    assert isinstance(rollout, str) and history.commit_exists(rollout), (
        "answers.rollout_commit must name a commit on this branch"
    )
    known_good = str(manifest["releases"]["known_good"]["tag"])
    candidate = str(manifest["releases"]["candidate"]["tag"])
    before = history.desired_state_at(f"{rollout}^")
    after = history.desired_state_at(rollout)
    assert before["release_tag"] == known_good and after["release_tag"] == candidate, (
        f"the rollout commit must change release_tag from {known_good} to {candidate}; "
        f"got {before['release_tag']!r} -> {after['release_tag']!r}"
    )
    changed = {key for key in history.DESIRED_STATE_KEYS if before[key] != after[key]}
    assert changed == {"release_tag"}, (
        "the rollout commit changes release_tag and nothing else; it also changed "
        f"{sorted(changed - {'release_tag'})}"
    )


def test_rollback_commit_is_a_revert_of_the_rollout_commit(answers: dict[str, Any]) -> None:
    """The rollback is `git revert` of the rollout: its message says so and its diff inverts it."""
    rollout = answers.get("rollout_commit")
    rollback = answers.get("rollback_commit")
    assert isinstance(rollout, str) and isinstance(rollback, str), (
        "answers.rollout_commit and answers.rollback_commit must both be recorded"
    )
    assert history.commit_exists(rollout) and history.commit_exists(rollback), (
        "both recorded commits must exist in this repository"
    )
    assert history.is_ancestor(rollout, rollback), "the rollback must come after the rollout"
    reverted = history.REVERT_LINE.search(history.commit_message(rollback))
    assert reverted is not None and reverted.group(1) == rollout, (
        "answers.rollback_commit must be the commit `git revert <rollout commit>` created, "
        "whose message says `This reverts commit <rollout commit>`; editing the tag back by "
        "hand and committing is a new change, not a rollback"
    )
    assert history.desired_state_at(rollback) == history.desired_state_at(f"{rollout}^"), (
        "the revert must restore the desired state exactly as it was before the rollout"
    )
    assert history.desired_state_at(f"{rollback}^") == history.desired_state_at(rollout), (
        "the revert must undo the rollout commit's desired state, not some later change"
    )


def test_recorded_observed_versions_are_the_manifest_build_versions(
    answers: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """The observed versions are the build_version each release stamps, not a tag typed by hand."""
    candidate = str(manifest["releases"]["candidate"]["build_version"])
    known_good = str(manifest["releases"]["known_good"]["build_version"])
    assert answers.get("rollout_observed_version") == candidate, (
        f"answers.rollout_observed_version must record the build_version the reconcile "
        f"record's first probe reported after the rollout ({candidate})"
    )
    assert answers.get("rollback_observed_version") == known_good, (
        f"answers.rollback_observed_version must record the build_version the reconcile "
        f"record's first probe reported after the revert ({known_good})"
    )


def test_drift_fields_name_desired_state_keys_the_check_can_report(
    answers: dict[str, Any],
) -> None:
    """Every recorded drift field is a dotted key the desired state declares."""
    fields = answers.get("drift_fields")
    assert isinstance(fields, list) and fields, (
        "answers.drift_fields must list at least one dotted key the first "
        "poe reconcile-check reported in Step 2"
    )
    unknown = [field for field in fields if field not in history.DESIRED_STATE_KEYS]
    assert not unknown, (
        f"answers.drift_fields names keys the check never reports: {unknown}; the desired "
        f"state declares {', '.join(history.DESIRED_STATE_KEYS)}"
    )


def test_head_worker_settings_match_the_recorded_answers(
    answers: dict[str, Any], head_state: dict[str, Any]
) -> None:
    """HEAD's worker.replicas and worker.restart_policy are the values the answers record."""
    replicas = answers.get("worker_replicas")
    assert isinstance(replicas, int) and not isinstance(replicas, bool) and replicas >= 2, (
        "answers.worker_replicas must be a whole number of at least 2"
    )
    assert head_state["worker.replicas"] == replicas, (
        f"worker.replicas at HEAD is {head_state['worker.replicas']!r}, but "
        f"answers.worker_replicas records {replicas}"
    )
    policy = answers.get("worker_restart_policy")
    assert policy in history.RESTART_POLICIES, (
        f"answers.worker_restart_policy must be one of {', '.join(history.RESTART_POLICIES)}"
    )
    assert head_state["worker.restart_policy"] == policy, (
        f"worker.restart_policy at HEAD is {head_state['worker.restart_policy']!r}, but "
        f"answers.worker_restart_policy records {policy!r}"
    )


@pytest.mark.runtime
def test_reconcile_to_head_then_check_reports_no_drift(
    head_state: dict[str, Any], manifest: dict[str, Any]
) -> None:
    """One `poe reconcile` pass at HEAD leaves `poe reconcile-check` with nothing to report."""
    try:
        record = history.run_reconciler("apply")
    except history.HistoryError as exc:
        pytest.fail(str(exc))
    assert record["commit"] == history.git("rev-parse", "HEAD"), (
        "the reconciler must read the desired state from HEAD"
    )
    assert record["first_probe"]["ready_status"] == 200, (
        f"the first probe after the reconcile pass saw {record['first_probe']['ready_status']}, "
        "not 200"
    )
    expected = history.manifest_tags(manifest)[str(head_state["release_tag"])]
    assert record["first_probe"]["build_version"] == expected, (
        f"/version answered {record['first_probe']['build_version']!r} after reconciling to "
        f"HEAD, whose release_tag stamps build_version {expected}"
    )
    try:
        check = history.run_reconciler("check")
    except history.HistoryError as exc:
        pytest.fail(str(exc))
    assert check["differences"] == [] and check["drift"] is False, (
        f"poe reconcile-check still reports drift after one reconcile pass: {check['differences']}"
    )


@pytest.mark.runtime
def test_running_stack_matches_the_committed_worker_settings(
    head_state: dict[str, Any],
) -> None:
    """Docker compose ps and docker inspect agree with the worker and api settings at HEAD."""
    records = history.compose_records()
    workers = [entry for entry in records if entry.get("Service") == "worker"]
    apis = [entry for entry in records if entry.get("Service") == "api"]
    assert len(workers) == head_state["worker.replicas"], (
        f"docker compose ps lists {len(workers)} worker container(s); HEAD commits "
        f"worker.replicas {head_state['worker.replicas']}"
    )
    assert apis, "docker compose ps lists no api container"
    for service, entries in (("worker", workers), ("api", apis)):
        expected = head_state[f"{service}.restart_policy"]
        for entry in entries:
            reported = history.restart_policy(str(entry["Name"]))
            assert reported == expected, (
                f"docker inspect reports restart policy {reported!r} on {entry['Name']}; "
                f"HEAD commits {service}.restart_policy {expected!r}"
            )
