"""Coldline.

===================

File:              tests/contract/test_submission.py
Component:         Contract tests — Test Submission
Purpose:           Tests for the public answer and path checks for this Task's submission.
Interacts With:    Published interfaces and repository boundaries
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Compatibility, ownership, export safety
Tools:             Python 3.12, pytest
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.contract.submission_validation import (
    SubmissionError,
    _load_one_document,
    main,
    validate_changed_paths,
    validate_submission,
)

ROOT = Path(__file__).parents[2]
SCHEMA = ROOT / "docs/contracts/submission.schema.json"
RECORD = "docs/student/task-3-8-gitops-record.md"


def _platform(**overrides: Any) -> dict[str, Any]:
    """Return one well-formed platform entry."""
    entry: dict[str, Any] = {
        "desired_state_source": "service_definition",
        "drift_correction": "none",
        "rollback_by": "previous_definition",
        "note": "Fictional format example; it states no platform's real behavior.",
    }
    entry.update(overrides)
    return entry


def valid_answers(**overrides: Any) -> dict[str, object]:
    """Return a complete answer sheet in the published shape."""
    answers: dict[str, Any] = {
        "rollout_commit": "1" * 40,
        "rollout_observed_version": "3.1.1",
        "drift_fields": ["release_tag", "worker.replicas"],
        "rollback_commit": "2" * 40,
        "rollback_observed_version": "3.1.0",
        "worker_replicas": 2,
        "worker_restart_policy": "on-failure",
        "platform_comparison": {
            "kubernetes_deployment": _platform(
                desired_state_source="git", rollback_by="git_revert"
            ),
            "argo_cd": _platform(),
            "eks": _platform(desired_state_source="git", rollback_by="git_revert"),
            "ecs": _platform(desired_state_source="git", rollback_by="revision_history"),
        },
        "recommendation": "Fictional format example; it recommends nothing.",
    }
    answers.update(overrides)
    return {"answers": answers}


def _task_root(tmp_path: Path, submission_text: str) -> Path:
    """Stage a minimal Task root the public verifier can validate."""
    (tmp_path / "docs/contracts").mkdir(parents=True)
    (tmp_path / "submission.yaml").write_text(submission_text, encoding="utf-8")
    (tmp_path / "submission-sample.yaml").write_text(
        (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "docs/contracts/submission.schema.json").write_text(
        SCHEMA.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def _with_record(root: Path, text: str) -> None:
    """Place a GitOps record with the given text beside the staged answer sheet."""
    (root / "docs/student").mkdir(parents=True, exist_ok=True)
    (root / RECORD).write_text(text, encoding="utf-8")


def test_a_complete_sheet_is_well_formed(tmp_path: Path) -> None:
    """The public schema accepts a complete sheet without judging its correctness."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))

    validate_submission(root / "submission.yaml", SCHEMA)


def test_blank_template_fails_with_field_address(tmp_path: Path) -> None:
    """An untouched answer sheet must identify the first incomplete field."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )

    with pytest.raises(SubmissionError, match="answers.rollout_commit"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"rollout_commit": "abc123"}, "rollout_commit"),
        ({"rollback_commit": "A" * 40}, "rollback_commit"),
        ({"rollout_observed_version": "candidate"}, "rollout_observed_version"),
        ({"drift_fields": []}, "drift_fields"),
        ({"drift_fields": ["worker.image"]}, "drift_fields"),
        ({"worker_replicas": 1}, "worker_replicas"),
        ({"worker_replicas": "two"}, "worker_replicas"),
        ({"worker_restart_policy": "on-exit"}, "worker_restart_policy"),
        ({"worker_restart_policy": False}, "worker_restart_policy"),
        ({"recommendation": "x" * 601}, "recommendation"),
    ],
    ids=[
        "short-sha",
        "uppercase-sha",
        "tag-word",
        "no-drift-fields",
        "unknown-drift-key",
        "single-replica",
        "prose-replicas",
        "unknown-policy",
        "unquoted-no",
        "long-recommendation",
    ],
)
def test_values_outside_the_published_contract_are_rejected(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    """The public schema must name the field it rejected, and reject the right ones."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(**overrides)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "platform,overrides,message",
    [
        ("argo_cd", {"desired_state_source": "helm"}, "argo_cd.desired_state_source"),
        ("ecs", {"drift_correction": "sometimes"}, "ecs.drift_correction"),
        ("eks", {"rollback_by": "kubectl"}, "eks.rollback_by"),
        ("kubernetes_deployment", {"note": "n" * 301}, "kubernetes_deployment.note"),
        ("kubernetes_deployment", {"note": ""}, "kubernetes_deployment.note"),
    ],
    ids=["source", "correction", "rollback", "long-note", "blank-note"],
)
def test_platform_entries_outside_the_published_contract_are_rejected(
    tmp_path: Path, platform: str, overrides: dict[str, Any], message: str
) -> None:
    """A nested enumeration or note cannot hide behind the top-level checks."""
    comparison = dict(valid_answers()["answers"]["platform_comparison"])  # type: ignore[index]
    comparison[platform] = _platform(**{**comparison[platform], **overrides})
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(platform_comparison=comparison)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_a_missing_platform_is_rejected(tmp_path: Path) -> None:
    """All four platforms are required; three of them is not a comparison."""
    comparison = dict(valid_answers()["answers"]["platform_comparison"])  # type: ignore[index]
    del comparison["ecs"]
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(platform_comparison=comparison)))

    with pytest.raises(SubmissionError, match="ecs"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "field",
    ["reconcile_passed", "instructor_approved", "defense_recording_url", "notes"],
)
def test_no_self_attestation_or_recording_field_is_accepted(tmp_path: Path, field: str) -> None:
    """Reject a self-approval, a pass boolean, or a recording URL."""
    answers = valid_answers()
    mapping = answers["answers"]
    assert isinstance(mapping, dict)
    mapping[field] = True
    root = _task_root(tmp_path, yaml.safe_dump(answers))

    with pytest.raises(SubmissionError, match="Additional properties"):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_exact_sample_copy_is_rejected(tmp_path: Path) -> None:
    """The published sample must not be accepted as a student submission."""
    root = _task_root(tmp_path, (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"))

    with pytest.raises(SubmissionError, match="fictional sample"):
        validate_submission(
            root / "submission.yaml",
            SCHEMA,
            sample_path=root / "submission-sample.yaml",
        )


def test_only_the_three_permitted_paths_may_change() -> None:
    """The desired state, the answer sheet, and the GitOps record; nothing else."""
    validate_changed_paths(["deploy/desired-state.yaml", "submission.yaml", RECORD])

    for protected in (
        "infra/gitops/reconcile.py",
        "infra/release/manifest.yaml",
        "compose.yaml",
        "deploy/.reconcile-override.yaml",
        "tests/contract/test_gitops_contract.py",
        "tests/student/test_my_loop.py",
        ".github/workflows/task.yml",
        "docs/student/runbook.md",
        "pyproject.toml",
        "README.md",
    ):
        with pytest.raises(SubmissionError, match="protected path changed"):
            validate_changed_paths([protected])


def test_public_entrypoint_reports_an_incomplete_answer_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catch a verifier entrypoint that skips the real submission contract."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )
    _with_record(root, (ROOT / RECORD).read_text(encoding="utf-8"))

    assert main(root, changed_paths=[]) == 1
    assert "answers.rollout_commit is incomplete" in capsys.readouterr().err


def test_public_entrypoint_rejects_an_untouched_gitops_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A complete answer sheet with the template record still in place is incomplete."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))
    _with_record(root, (ROOT / RECORD).read_text(encoding="utf-8"))

    assert main(root, changed_paths=[]) == 1
    assert "template markers" in capsys.readouterr().err


def test_public_entrypoint_accepts_a_completed_sheet_and_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With every marker replaced and the paths inside the boundary, the check passes."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))
    _with_record(root, "# Task 3.8 GitOps record\n\n## Step 1\n\nMy own evidence.\n")

    assert main(root, changed_paths=["deploy/desired-state.yaml", "submission.yaml"]) == 0
    assert "Task 3.8 answer verification passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "answers: {value: first, value: second}\n",
        "answers: &answer {value: fictional}\n",
        "answers: *missing\n",
        "answers: {<<: {value: fictional}}\n",
        "answers: {value: 2026-09-04}\n",
        "answers: {value: !custom fictional}\n",
        "answers: {1: fictional}\n",
    ],
    ids=["duplicate-key", "anchor", "alias", "merge-key", "date", "custom-tag", "non-string-key"],
)
def test_non_json_yaml_constructs_are_rejected(tmp_path: Path, unsafe_text: str) -> None:
    """Reject restricted syntax before schema validation can mask a parser defect."""
    submission = tmp_path / "submission.yaml"
    submission.write_text(unsafe_text, encoding="utf-8")

    with pytest.raises(SubmissionError, match="restricted YAML"):
        _load_one_document(submission)


def test_multiple_yaml_documents_are_rejected(tmp_path: Path) -> None:
    """A second document cannot supply or replace the answer mapping."""
    submission = tmp_path / "submission.yaml"
    submission.write_text("answers: {}\n---\nanswers: {}\n", encoding="utf-8")

    with pytest.raises(SubmissionError, match="exactly one YAML mapping"):
        _load_one_document(submission)
