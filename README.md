# Coldline Task 3.8 — Optional Task 8: GitOps loop on Compose

This checkpoint is the complete, settled Coldline platform from Task 3.7, with one change to
how the running stack is allowed to change at all. A committed file, `deploy/desired-state.yaml`,
says which release the API, worker, and initializer run, how many worker replicas run, and which
restart policy the API and worker containers carry. A supplied reconciler reads that file from
git HEAD and makes the Compose stack match it. Nobody types a release into a terminal anymore:
you roll forward by commit, catch and correct a change made by hand, roll back with a revert,
change the worker's restart policy and replica count by commit, and record how Kubernetes
Deployments, Argo CD, EKS, and ECS would each provide, or not provide, the same loop. This Task
is optional and adds no code.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/tripleten-com/ai-system-engineering-curriculum-sprint-3-task-3-8/tree/main)

## Start the system

Prerequisites are Python 3.12, git, and Docker with Compose v2. The supplied bootstrap supports
macOS arm64/x86-64, Windows x86-64, and Linux x86-64/aarch64, and installs pinned uv 0.11.8
under `.tools/bin`. If your computer cannot run the stack locally, use the Codespaces button
above.

On macOS and most Linux distributions the interpreter is `python3`; substitute it wherever these
commands say `python`.

```shell
python infra/scripts/bootstrap.py
./.tools/bin/uv sync --frozen
./.tools/bin/uv run --frozen poe preflight
./.tools/bin/uv run --frozen poe start
./.tools/bin/uv run --frozen poe ready
./.tools/bin/uv run --frozen poe ingest
./.tools/bin/uv run --frozen poe release-build
```

PowerShell and POSIX wrappers are available under `infra/scripts/`. After uv is on `PATH`, the
shorter `uv run --frozen poe <task>` form works.

| Service | Local URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | Submit exception workflows and retrieval queries; `/version` names the build that answers |
| Grafana | `http://localhost:3000` | Use the focused diagnostics dashboard |
| Prometheus | `http://localhost:9090` | Query bounded metrics and inspect the deployed alert rule |
| Alertmanager | `http://localhost:9093` | Inspect firing and resolved alerts |
| Jaeger | `http://localhost:16686` | Inspect local traces |
| LocalStack S3/SQS | `http://localhost:4566` | Inspect the emulated object-storage and queue endpoint |

Each of these ports can be overridden by setting the matching `COLDLINE_API_HOST_PORT`,
`COLDLINE_GRAFANA_HOST_PORT`, `COLDLINE_PROMETHEUS_HOST_PORT`, `COLDLINE_ALERTMANAGER_HOST_PORT`,
`COLDLINE_JAEGER_HOST_PORT`, or `COLDLINE_LOCALSTACK_HOST_PORT` environment variable in your shell
environment or a local `.env` file (copy `.env.example`) if a default collides with something
already running on your machine. Keep the override in place for every `poe` command; the
reconciler reads `COLDLINE_API_HOST_PORT` the same way for its readiness probe.

This Task runs as its own Compose project, `coldline-task-3-8`. If an earlier Task's stack is
still running, run `poe stop` in that Task's repository first; otherwise `poe start` here fails
because the published ports are already taken.

PostgreSQL, Redis, worker metrics, and OTLP remain inside the Compose network. Codespaces uses the
same `compose.yaml` and keeps every forwarded port private. Redis keeps running in this Task only
for an earlier checkpoint's own contract test; no composition root reads it anymore.

## Command path

For this Task, run the supplied commands in this order:

```text
poe start
poe ready
poe ingest
poe release-build
poe reconcile-check
poe reconcile
poe verify
```

Between `poe reconcile-check` and `poe verify` sit the four loops the lesson walks you through:
commit, `poe reconcile`, observe; change the stack by hand, `poe reconcile-check`,
`poe reconcile`, `poe reconcile-check`; `git revert`, `poe reconcile`; commit the policy and
replica change, `poe reconcile`, `poe reconcile-check`.

| Command | Use |
|---|---|
| `poe release-build` | Build both manifest releases (`3.1.0` and `3.1.1`) for the API and worker images from this source, so the reconciler has both to select from |
| `poe reconcile-check` | Read `deploy/desired-state.yaml` from git HEAD, compare it with the running Compose services, and print the record; change nothing |
| `poe reconcile` | One reconcile pass: read HEAD, apply every difference through Docker Compose behind the API readiness gate (`--no-build --wait`), and print the record |
| `poe answers` | The static half of this Task's own check: the answer sheet's format, the GitOps record's template markers, and the diff from your merge base against the three permitted files |
| `poe gitops-checks` | The assessed checks: your branch history and answers, then one reconcile pass at HEAD after which `poe reconcile-check` must report no drift |
| `poe gitops-contract` | `poe answers` and `poe gitops-checks` together; the check `poe verify` runs for this Task |
| `poe verify` | The public student verification path: it starts the stack, ingests the corpus, builds both releases, runs `poe gitops-contract`, then the smoke tests, the end-to-end workflow, and the supplied student tests |
| `poe queue-contract`, `poe slo-contract`, `poe gate-contract`, `poe runbook-contract` | The inherited Task 3.3 through 3.6 checks over the settled checkpoint; still runnable, not part of this Task's verify path |
| `poe contract` | Check interfaces, boundaries, submissions, and repository structure |
| `poe smoke` | Check the initialized running platform |
| `poe e2e` | Run the external API-to-worker workflow |
| `poe student-tests` | Run the supplied tests under `tests/student/`; this Task permits no additions there |
| `poe dev-failure-lab`, `poe trigger-alert-load`, `poe verify-alert-recovery`, `poe inject-failure`, `poe redrive` | Inherited exercises from Tasks 3.3, 3.4, and 3.6, still runnable; not part of this Task |
| `poe restart` | Restart the existing API and worker containers **without rebuilding** |
| `poe stop` | Remove containers and the network, keeping named volumes |
| `poe reset` | Remove containers, the network, and local named volumes |

For Task 3.8, `poe verify` starts the stack, ingests the supplied corpus, builds both releases,
runs `poe answers`, runs the GitOps checks (which reconcile the running stack to HEAD, so expect
a few minutes), then the smoke tests and the end-to-end exception workflow against the
reconciled stack, and the supplied student tests. The inherited Task 3.3 through 3.6 checks are
not in this path: `poe gitops-contract` moves the stack to whatever HEAD commits, including the
worker replica count and restart policy, and those checks were qualified against the settled
single-replica checkpoint. They remain runnable on their own.

## The desired state and the reconciler

`deploy/desired-state.yaml` is the only file you change to change the stack. As supplied it
describes the checkpoint exactly as it runs after `poe start`:

```yaml
release_tag: "3.1.0"
api:
  restart_policy: unless-stopped
worker:
  restart_policy: unless-stopped
  replicas: 1
```

The comments in the file say what each restart policy does when a container exits. The
reconciler, `infra/gitops/reconcile.py`, is supplied and protected. It reads the file with
`git show HEAD:deploy/desired-state.yaml`, never from your working tree, so an uncommitted edit
changes nothing. It observes the running services with `docker compose ps` and `docker inspect`,
compares four dotted keys (`release_tag`, `api.restart_policy`, `worker.restart_policy`,
`worker.replicas`), and prints one JSON record. On a reconcile pass it applies every difference
in one Compose command: the tag through `COLDLINE_RELEASE_TAG`, the replica count through
`--scale worker=N`, and the two restart policies through a generated, git-ignored
`deploy/.reconcile-override.yaml`, with `--no-build --wait` so the pass returns only when the
API readiness gate from Task 1 passes. The record names the commit it read, the differences as
desired versus observed, the actions, how long Compose waited, and the first readiness probe
with the `build_version` that `/version` answered. Drift is reported in the record; the exit
code is non-zero only for a real failure such as an unreadable HEAD, a tag the manifest does not
name, or a Compose error.

`poe start` still rebuilds the first-party images from source with `--build` and recreates the
containers from `compose.yaml` alone, so after a `poe start` the running stack may drift from a
HEAD that commits a different tag, replica count, or restart policy. That is what `poe reconcile`
is for, and `poe verify` runs it before anything else that reads the stack.

## Folder map

```text
repository root/
├── deploy/              The committed desired state this Task's reconciler reads from HEAD
├── docs/                Student guidance, public contracts, and fidelity notes
│   ├── contracts/       Machine-readable public contracts
│   ├── fidelity/        Local-runtime boundary notes, including the settled JobQueue record
│   ├── architecture/    Supplied vector engine technical profiles, in prose
│   ├── retrieval/       Supplied retrieval pipeline reference
│   └── student/         This Task's contract and GitOps record, and the supplied Task 6 runbook
├── config/              Retrieval configuration, settled and supplied from Sprint 2
├── infra/               Local setup and runtime configuration
│   ├── containers/      The API and worker Dockerfiles, with the build identity arguments
│   ├── gitops/          The supplied reconciler: release build, drift check, reconcile pass
│   ├── observability/   Prometheus, Alertmanager, and Grafana configuration
│   ├── release/         The supplied Task 3.1 release manifest, unchanged
│   ├── corpus/          Supplied synthetic corpus, query set, and designated investigation
│   ├── judge/           Supplied cached judge evidence and its provenance record
│   ├── profiles/        Supplied engine and emulator profiles, and their provenance record
│   └── postgres/        Database initialization and the migration baseline stamp
├── loadtest/            Supplied traffic profile and provider-latency harness
├── migrations/          Alembic environment, revision template, and revisions
├── src/
│   ├── api/             HTTP application code, the retrieval and document paths, composition
│   ├── worker/          Background application code, including the dead-letter depth poller
│   ├── domain/          Shared domain code, contracts, the failure taxonomy, service and repository contracts
│   ├── ports/           Application interfaces
│   └── adapters/        Technology-specific implementations, including the supplied SQS/DLQ queue adapter
└── tests/
    ├── unit/            Isolated behavior checks
    ├── benchmark/       Supplied evaluation harness, metrics, and adoption policy
    ├── contract/        Interface, retrieval, and repository checks, and this Task's GitOps checks
    ├── diagnostics/     Supplied stage inspector
    ├── doubles/         Supplied deterministic test doubles
    ├── failure/         Supplied failure-lab and exercise scripts from Tasks 3.3, 3.4, and 3.6 — not this Task's work
    ├── student/         Supplied student tests; no additions in this Task
    ├── smoke/           Running-platform checks
    └── e2e/             Supplied workflow tools and checks
```

## Overview

Use the Optional Task 8 lesson (Task 3.8 in this repository) to decide what to do. This README
covers local setup and repository orientation.

1. `README.md` — local setup, commands, and permitted changes.
2. [`docs/student/task-3-8-contract.md`](docs/student/task-3-8-contract.md) — what this Task
   assesses and who assesses it, the five Steps, the commands, the mapping from the lesson's
   Check-list to each check, and the three permitted paths.
3. [`deploy/desired-state.yaml`](deploy/desired-state.yaml) — the committed desired state; the
   comments explain each key.
4. [`docs/student/task-3-8-gitops-record.md`](docs/student/task-3-8-gitops-record.md) — the
   record template, one section per loop; replace every marker with your own evidence.
5. [`infra/release/manifest.yaml`](infra/release/manifest.yaml) — the two releases the
   reconciler can select from, unchanged since Task 3.1.

The application source lives in five flat packages:

| Package | Responsibility |
|---|---|
| `api` | HTTP delivery, API use cases, the retrieval workflow, versioned routes, configuration, and composition |
| `worker` | Background processing, retries, the dead-letter depth poller, configuration, and composition |
| `domain` | Provider-neutral contracts, state rules, identity, redaction, embedding, chunking, fusion, access constraints, failure classification, service and repository contracts |
| `ports` | Exactly five visible application interfaces |
| `adapters` | PostgreSQL, pgvector retrieval, LocalStack SQS/DLQ, S3-compatible object storage, deterministic model, the resilient model-provider wrapper, logs, traces |

`src/api/bootstrap.py` and `src/worker/bootstrap.py` compose each process from its settings and
adapters. Process settings live in `src/api/config.py` and `src/worker/config.py`.

## The five ports

Find the available interfaces in `src/ports/`. A port describes an application capability; an
adapter provides it using a concrete technology.

| Port | General responsibility |
|---|---|
| `ModelProvider` | Call an AI model service |
| `Retriever` | Look up relevant context or documents |
| `ObjectStore` | Store large binary objects or files |
| `JobQueue` | Publish and consume background work |
| `SecretProvider` | Read API keys and credentials |

LocalStack SQS, with a bound dead-letter queue, still carries `JobQueue`, unchanged from Task 3.3.
Every worker replica you commit consumes the same queue; see
[JobQueue fidelity](docs/fidelity/JobQueue.md) for what that does and does not prove.

## Test levels

| Level | Requires Compose | Main question |
|---|---:|---|
| Unit | No | Does one responsibility behave correctly, including failures? |
| Contract | Some | Do interfaces, schemas, paths, and dependency rules stay compatible? |
| Smoke | Yes | Did the complete local platform initialize and become observable? |
| E2E | Yes | Can an external client complete the supplied workflow? |

Contract checks marked `runtime` need the running stack, and checks marked `assessed` read your
work. `poe contract` skips both; `poe gitops-checks` runs this Task's own module, whose history
checks need git and whose two runtime checks need the stack. A fresh Task 3.8 checkout fails the
history and answer checks, because the rollout, the revert, the policy commit, and the answers
are this Task's work; its two runtime checks pass, because the supplied desired state matches the
stack `poe start` brings up.

## Submission checks

Run `poe verify` locally before opening your student pull request. Public GitHub CI repeats
the student checks, running `poe answers` first so a boundary violation fails fast, then
`poe start`, `poe ingest`, `poe release-build`, and `poe verify`. The observed versions and the
twelve platform enumerations in `answers.platform_comparison` are compared with a protected
answer key after you submit on the platform; the public checks confirm their format and their
allowed values only. Follow the Task lesson's submission policy: this Task is optional and
gates nothing.

## Task boundary

Task 3.8 asks you to move the stack through four loops by commit alone, fill the answer sheet,
and complete the GitOps record. The only student-editable paths are:

- `deploy/desired-state.yaml`
- `submission.yaml`
- `docs/student/task-3-8-gitops-record.md`

Change the stack only through the desired state, with one exception: Step 2, where you change
the running stack by hand on purpose so the reconciler can catch it. Keep the reconciler
(`infra/gitops/reconcile.py`), `compose.yaml`, `infra/release/manifest.yaml`, the transport
adapters, every test file, and both workflows exactly as supplied; do not edit the reconciler to
make a Step pass. The generated `deploy/.reconcile-override.yaml` is git-ignored and is never
yours to commit. The public check compares the diff from your merge base against the three
permitted files and reports any other change as a boundary violation.

### Student walkthrough

See **Optional Task 8: GitOps loop on Compose** in your course platform for the full
walkthrough. In outline: read `docs/student/task-3-8-contract.md`, start the stack and build
both releases, create a feature branch, run `poe reconcile-check` for your baseline, then work
the four loops, committing `deploy/desired-state.yaml` before each `poe reconcile` and pasting
each record into the matching Step of `docs/student/task-3-8-gitops-record.md`; fill
`submission.yaml` from your own commits and records and from each platform's documented
behavior; check `git diff --stat` shows only the three permitted files; run `poe verify`; open
your pull request and submit on the platform.

## Operational limits

This local system does not authenticate users, terminate TLS, or manage production secrets.
The Compose PostgreSQL password and the LocalStack access keys are local-only non-secret
credentials. Never place real credentials, personal data, or production records in this
repository.

Alertmanager here is configured with a "default" receiver that has no notification integration:
alerts are queryable through its own API but never sent anywhere real. Never add a webhook, email,
Slack, or paid integration; Sprints 1-4 are emulator-only and never call a hosted endpoint. Do
not install Kubernetes, EKS, Helm, or Argo CD, and do not create paid cloud resources; Step 5
compares those platforms in text only.

The reconciler is a loop with a person in it: it runs when you run it, and it compares only the
keys the desired state declares. A hand change to something the file does not describe, such as
an environment variable, is invisible to it. A rollout here recreates containers on one host
from a local image tag; it makes no claim about registries, image digests, schedulers, or how
any managed platform behaves. See [JobQueue fidelity](docs/fidelity/JobQueue.md) for what
LocalStack SQS does not prove about managed SQS and ECS.

Named volumes preserve local PostgreSQL, Redis, Prometheus, Alertmanager, Grafana, and Jaeger state
across `poe stop`. LocalStack object and queue contents are deliberately not persisted; the
initializer re-uploads the supplied corpus artifacts and re-provisions the queue on every start.
The `poe reset` command deletes the named volumes. This topology makes no backup, replication,
high-availability, disaster-recovery, capacity, latency-SLO, or availability claim beyond the one
alert Task 3.4 configures, the one CI gate Task 3.5 wires to it, and the one bounded recovery
Task 3.6's failure lab demonstrates.

See [JobQueue fidelity](docs/fidelity/JobQueue.md),
[ModelProvider fidelity](docs/fidelity/ModelProvider.md),
[ObjectStore fidelity](docs/fidelity/ObjectStore.md), and
[Retriever fidelity](docs/fidelity/Retriever.md) for the active adapter boundaries. The
[local runtime evidence](docs/fidelity/local-runtime.md) records the current measurement and its
qualification limits.
