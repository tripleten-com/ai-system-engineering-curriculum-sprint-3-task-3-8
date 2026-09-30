<!--
Never exported. Known-wrong variant: this record is the reference completion's, unchanged.
The variant's defect is in the rollback commit the qualifier makes (a hand edit of the tag
instead of `git revert`), not in the record, so the record stays complete and only the
revert check fails.
-->
# Task 3.8 GitOps record

This record is the answer to Elena's question about what was running and why. Every record
below is the reconciler's own output on my branch, followed by what I observed with `curl`,
`docker compose ps`, and `docker inspect`.

## Step 1 - Roll out the candidate by commit

Baseline, before any change, `poe reconcile-check` at the materialization commit:

```json
{
  "commit": "<baseline commit>",
  "desired": {"release_tag": "3.1.0", "api.restart_policy": "unless-stopped",
              "worker.restart_policy": "unless-stopped", "worker.replicas": 1},
  "observed": {"release_tag": "3.1.0", "api.restart_policy": "unless-stopped",
               "worker.restart_policy": "unless-stopped", "worker.replicas": 1},
  "differences": [],
  "drift": false,
  "mode": "check",
  "probe": {"build_version": "3.1.0", "ready_status": 200}
}
```

Rollout commit `<rollout commit>` ("Roll the API and worker forward to 3.1.1"): the one-line
diff on `deploy/desired-state.yaml` changes `release_tag` from `"3.1.0"` to `"3.1.1"`.
`poe reconcile` record:

```json
{
  "commit": "<rollout commit>",
  "differences": [{"key": "release_tag", "desired": "3.1.1", "observed": "3.1.0"}],
  "actions": [
    "release_tag: set COLDLINE_RELEASE_TAG=3.1.1 and recreate api and worker (and the initializer they depend on) from the 3.1.1 images",
    "COLDLINE_RELEASE_TAG=3.1.1 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=1 api worker"
  ],
  "compose_wait_seconds": 27.4,
  "first_probe": {"build_version": "3.1.1", "ready_status": 200},
  "mode": "reconcile",
  "observed": {"release_tag": "3.1.1", "api.restart_policy": "unless-stopped",
               "worker.restart_policy": "unless-stopped", "worker.replicas": 1}
}
```

Compose waited about 27 seconds: the candidate answers 503 on `/health/ready` for its 20-second
warm-up and the gate held the pass until it served. `curl http://localhost:8000/version`
answered `{"service": "coldline-api", "build_version": "3.1.1", "ready": true}`, and
`docker compose --profile observability --profile localstack ps` listed `api` and `worker` on
`coldline-api:3.1.1` and `coldline-worker:3.1.1`.

## Step 2 - Catch and correct a change made by hand

Hand change, no commit:
`docker compose --profile observability --profile localstack up -d --no-build --scale worker=2 worker`.

First `poe reconcile-check`:

```json
{
  "commit": "<rollout commit>",
  "differences": [
    {"key": "release_tag", "desired": "3.1.1", "observed": "api=3.1.1, initializer=3.1.0, worker=3.1.0"},
    {"key": "worker.replicas", "desired": 1, "observed": 2}
  ],
  "drift": true,
  "mode": "check"
}
```

I intended to add one worker. The check found two things: the extra replica, and that both
workers (and the initializer they depend on) had been recreated from `3.1.0`, because a plain
Compose command with no `COLDLINE_RELEASE_TAG` in the shell resolves the image from the file's
default tag. `poe reconcile` then applied both differences without a commit (HEAD still says
one worker at `3.1.1`), and the second `poe reconcile-check` reported `"differences": []`,
`"drift": false`, with `docker compose ps` showing one `worker` on `coldline-worker:3.1.1`.

What this loop proves: the check catches a change to any key the desired state declares. What
it does not: a hand change to something the file does not describe, such as a worker
environment variable, would be invisible to it.

## Step 3 - Roll back with a revert

`git revert <rollout commit>` created `<rollback commit>` with the generated message
`Revert "Roll the API and worker forward to 3.1.1"` and the line
`This reverts commit <rollout commit>.` `git log --oneline -3` shows the revert above the
rollout above the baseline. `poe reconcile` record:

```json
{
  "commit": "<rollback commit>",
  "differences": [{"key": "release_tag", "desired": "3.1.0", "observed": "3.1.1"}],
  "compose_wait_seconds": 6.8,
  "first_probe": {"build_version": "3.1.0", "ready_status": 200},
  "mode": "reconcile"
}
```

The known-good build has no warm-up, so the wait was shorter than in Step 1. `/version`
answered `"build_version": "3.1.0"`.

## Step 4 - Set the restart policy and replica count by commit

Policy commit `<policy commit>` ("Run two workers and restart a failed one"): one diff on
`deploy/desired-state.yaml` setting `worker.replicas` to `2` and `worker.restart_policy` to
`on-failure`. I chose `on-failure` because a worker that dies partway through a summary during
peak season exits with an error and should come back on its own, while a worker that exits
cleanly after `poe worker-stop` should stay stopped for the engineer who stopped it.
`poe reconcile` record:

```json
{
  "commit": "<policy commit>",
  "differences": [
    {"key": "worker.restart_policy", "desired": "on-failure", "observed": "unless-stopped"},
    {"key": "worker.replicas", "desired": 2, "observed": 1}
  ],
  "actions": [
    "worker.restart_policy: write restart on-failure into deploy/.reconcile-override.yaml and recreate worker with it",
    "worker.replicas: scale worker to 2 (--scale worker=2)",
    "COLDLINE_RELEASE_TAG=3.1.0 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=2 api worker"
  ],
  "compose_wait_seconds": 9.1,
  "first_probe": {"build_version": "3.1.0", "ready_status": 200},
  "mode": "reconcile",
  "observed": {"release_tag": "3.1.0", "api.restart_policy": "unless-stopped",
               "worker.restart_policy": "on-failure", "worker.replicas": 2}
}
```

`docker compose --profile observability --profile localstack ps` listed two `worker`
containers, `coldline-task-3-4-worker-1` and `coldline-task-3-4-worker-2`, both on
`coldline-worker:3.1.0`. `docker inspect` on each id reported a `RestartPolicy` name of
`on-failure`. The final `poe reconcile-check` reported `"differences": []`,
`"drift": false`. HEAD describes the stack I leave running.
