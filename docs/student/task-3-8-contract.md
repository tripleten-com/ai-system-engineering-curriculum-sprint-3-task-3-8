# Task 3.8 — GitOps loop on Compose contract

Your repository is the finished Project 3 system. This Task changes how the running stack is
allowed to change at all: one committed file describes what should run, and a supplied
reconciler makes the stack match it. You roll the API and worker forward by commit, catch and
correct a change made by hand, roll back with a revert, change the worker's restart policy and
replica count by commit, and record how four platforms would provide, or not provide, the same
loop. You write no application code, and you never edit the reconciler.

## What is assessed, and by whom

| Assessed | By |
|---|---|
| The pull request changes only `deploy/desired-state.yaml`, `submission.yaml`, and `docs/student/task-3-8-gitops-record.md` | Automated, in this repository (`poe answers`, and `poe verify` repeats it) |
| The answer sheet has the published shape, every enumerated field holds an allowed value, and the GitOps record has no template marker left | Automated (same command) |
| `deploy/desired-state.yaml` at HEAD keeps the supplied keys and names a manifest release tag | Automated, in this repository, from git HEAD |
| `answers.rollout_commit` and `answers.rollback_commit` are two different full SHAs on your branch, the rollout changes only `release_tag` to the candidate, and the rollback is `git revert` of the rollout | Automated, in this repository, from your branch history |
| `answers.rollout_observed_version` and `answers.rollback_observed_version` are the build versions the two releases stamp | Automated, in this repository, against the manifest |
| `answers.drift_fields` names desired-state keys the check can report | Automated, in this repository |
| `answers.worker_replicas` and `answers.worker_restart_policy` match HEAD, and the running stack matches HEAD | Automated, in this repository, from HEAD and the running containers |
| After one `poe reconcile` pass at HEAD, `poe reconcile-check` reports no drift and the first probe is 200 from the build HEAD names | Automated, in this repository, by performing the pass |
| Your two observed versions and the twelve platform enumerations | Protected automated check, after you submit on the platform |
| Your GitOps record, your notes, and your recommendation | Your instructor, if the Add-On evidence is referenced at the Project Defense |

## The five Steps

### Step 1 — Roll out the candidate by commit

Build both releases with `poe release-build`. Run `poe reconcile-check` before changing
anything: the supplied desired state matches the running checkpoint, so it reports no drift.
Change `release_tag` in `deploy/desired-state.yaml` from `3.1.0` to `3.1.1` and nothing else,
commit, and run `poe reconcile`. Record the commit's full SHA and the `build_version` the
record's first probe reported.

### Step 2 — Catch and correct a change made by hand

Scale the worker by hand with a Compose command, run `poe reconcile-check`, then
`poe reconcile`, then `poe reconcile-check` again. No commit is involved: HEAD still says one
worker at `3.1.1`, so the reconciler restores it. Record every dotted key the first check
reported in `answers.drift_fields`.

### Step 3 — Roll back with a revert

Run `git revert <rollout commit>`, keep the generated message, and run `poe reconcile`. Record
the revert's full SHA and the `build_version` the record's first probe reported. Editing the
tag back by hand and committing is a new change, not a rollback: the check reads the revert
line git writes into the message, and the inverse diff.

### Step 4 — Set the restart policy and replica count by commit

Set `worker.replicas` to 2 or more and `worker.restart_policy` to a value other than the
committed one, in one commit, and run `poe reconcile`. Prove both with `docker compose ps` and
`docker inspect`, run `poe reconcile-check`, and record the two values. HEAD is the stack you
leave running.

### Step 5 — Compare the loop with Kubernetes, Argo CD, EKS and ECS

Fill `answers.platform_comparison` from each platform's documented behavior: where its desired
state lives, what corrects drift, how a rollback is expressed, and one note in Elena's terms.
Then write `answers.recommendation`. Nothing is installed; the answers are text, and the
enumerated values are checked against a protected answer key after you submit.

## Commands

```shell
poe release-build       # build both manifest releases (3.1.0 and 3.1.1) for api and worker
poe reconcile-check     # compare HEAD's desired state with the running stack; change nothing
poe reconcile           # one reconcile pass from HEAD, behind the readiness gate; print the record
poe answers             # the static half: answer format, record markers, permitted-path boundary
poe gitops-checks       # the assessed checks: branch history, answers, one reconcile pass at HEAD
poe gitops-contract     # both halves together; the check poe verify runs for this Task
poe verify              # the full public path
```

Start the stack per `README.md` first. `poe reconcile` and `poe gitops-contract` move the
running stack to whatever HEAD commits, so expect `poe verify` to take a few minutes. Both
reconciler commands print one JSON record on standard output: the commit SHA it read, the
desired and observed values under the four dotted keys (`release_tag`, `api.restart_policy`,
`worker.restart_policy`, `worker.replicas`), the differences, and, for a reconcile pass, the
actions applied, how long Compose waited, and the first readiness probe with the
`build_version` that `/version` answered. Drift is reported in the record, never as a failing
exit code; the exit code is non-zero only for a real failure.

## What the checks verify

Each row of the lesson's Check-list maps to one check:

| Check-list row | Check | What it looks at |
|---|---|---|
| `deploy/desired-state.yaml` at HEAD keeps the supplied keys, names a manifest release tag, and describes the stack you leave running | `test_desired_state_at_head_keeps_the_supplied_keys_and_names_a_manifest_tag` | `git show HEAD:deploy/desired-state.yaml`: the three top-level keys, four legal restart policies, a manifest tag, replicas of at least 1 |
| After one `poe reconcile` pass at HEAD, `poe reconcile-check` reports no drift | `test_reconcile_to_head_then_check_reports_no_drift` | Runs the reconciler's `apply`, then `check`, exactly as `poe` does; the commit read is HEAD, the first probe is 200 from the build HEAD's tag stamps, and the check's differences are empty |
| `answers.rollout_commit` and `answers.rollback_commit` are full 40-character commit SHAs from your branch, and they differ | `test_rollout_and_rollback_commits_are_distinct_full_shas_on_this_branch` | Both values match `^[0-9a-f]{40}$`, name commits this repository holds, are ancestors of HEAD, and differ |
| The rollout commit changed the tag (from the Step 1 check) | `test_rollout_commit_changes_the_release_tag_to_the_candidate` | The desired state at `<rollout>^` names `3.1.0` and at `<rollout>` names `3.1.1`, with no other key changed |
| `answers.rollback_commit` is the revert commit, not a fresh edit (from the Step 3 check) | `test_rollback_commit_is_a_revert_of_the_rollout_commit` | The rollout is an ancestor of the rollback, the rollback's message carries `This reverts commit <rollout>`, and its desired state equals the state before the rollout while its parent's equals the rollout's |
| `answers.rollout_observed_version` and `answers.rollback_observed_version` are the `build_version` values your reconcile records report | `test_recorded_observed_versions_are_the_manifest_build_versions` | The candidate and known-good `build_version` from `infra/release/manifest.yaml`, which are what the records report when the gate held |
| `answers.drift_fields` lists at least one dotted desired-state key that `poe reconcile-check` reported in Step 2 | `test_drift_fields_name_desired_state_keys_the_check_can_report` (and the schema) | A non-empty list whose members are among the four dotted keys |
| `answers.worker_replicas` is a whole number of at least 2 and `answers.worker_restart_policy` is one of the four policies, and both match HEAD | `test_head_worker_settings_match_the_recorded_answers` | HEAD's `worker.replicas` and `worker.restart_policy` against the two answers |
| ... and both match the running stack | `test_running_stack_matches_the_committed_worker_settings` | `docker compose ps` lists as many `worker` containers as HEAD commits; `docker inspect` reports HEAD's restart policy on each worker and api container |
| `answers.platform_comparison` holds all four platforms with every enumerated field from its allowed values and a non-empty note, and `answers.recommendation` is non-empty | `tests/contract/submission_validation.py` (`poe answers`) | The published schema: four required platforms, three enumerations each, a note of at most 300 characters, a recommendation of at most 600. The values themselves are compared with the protected answer key after you submit |
| The GitOps record replaces every template marker | `tests/contract/submission_validation.py` (`poe answers`) | `docs/student/task-3-8-gitops-record.md` no longer contains `_Write your evidence here._` |
| The pull request modifies only the three permitted files | `tests/contract/submission_validation.py` (`poe answers`) and `test_submission_change_stays_within_the_permitted_diff` | The diff from the merge base with `main` against the three-file allowlist, with no directory prefix exempted |

The history checks need git but no running stack; the two checks marked `runtime` need the
stack. `poe contract` skips this whole module because it is marked `assessed`; `poe
gitops-checks`, `poe gitops-contract`, and `poe verify` run it.

## Student-editable paths

- `deploy/desired-state.yaml`
- `submission.yaml`
- `docs/student/task-3-8-gitops-record.md`

That is the whole list. The reconciler (`infra/gitops/reconcile.py`), `compose.yaml`, the
release manifest, the transport adapters, every test, and both workflows stay as supplied. The
generated `deploy/.reconcile-override.yaml` is git-ignored and never yours to commit. Before you
push, run `git status` and `git diff --stat` against your merge base: if anything besides the
three files changed, the public check reports the boundary violation rather than your work.

## What this local loop does not prove

Compose plus a reconciler you run by hand is a loop with a person in it. The check compares
only the keys the desired state declares; a hand change to something the file does not
describe, such as an environment variable, is invisible to it. Your run proves the loop on one
host; it proves nothing about how Kubernetes, Argo CD, EKS, or ECS behave. Say so in your
record and in `answers.recommendation`.
