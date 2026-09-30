# Task 3.8 GitOps record

This record is the answer to Elena's question about what was running and why. It is not
graded by the automated checks; they read `submission.yaml`, your branch history, and the
running stack. Replace every italic placeholder line below with your own evidence;
`poe verify` fails while any placeholder remains. For each loop, paste the reconciler's
record as it printed it, the commit SHA it read, and what you observed afterwards with
`curl http://localhost:8000/version`, `docker compose ps`, or `docker inspect`. Keep the
outputs yours: every SHA and every record here comes from your own runs on your own branch.

## Step 1 - Roll out the candidate by commit

The `poe reconcile-check` output before you changed anything, then the rollout commit's
full SHA, the `poe reconcile` record (the one difference on `release_tag`, the actions,
how long Compose waited, the first probe and its `build_version`), and the `/version` and
`docker compose ps` outputs that confirm the candidate is serving.

Baseline, before I changed anything. `poe reconcile-check` at the checkpoint commit
`f1ef17ab8b33ac1ffea968bbcb54877bc42ae0cc`:

```text
Poe => python infra/gitops/reconcile.py check
commit f1ef17ab8b33: no drift
{
  "commit": "f1ef17ab8b33ac1ffea968bbcb54877bc42ae0cc",
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [],
  "drift": false,
  "mode": "check",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "probe": {
    "build_version": "3.1.0",
    "ready_status": 200
  },
  "recorded_at": "2026-09-30T01:07:03+00:00"
}
```

The rollout commit, full SHA `08f9b0129f1049caf1d8fa1fb12a0782df69a358`. Its whole diff is
one line, `release_tag` from `"3.1.0"` to `"3.1.1"` in `deploy/desired-state.yaml`.

`poe reconcile` after that commit:

```text
Poe => python infra/gitops/reconcile.py apply
commit 08f9b0129f10: applied 1 difference(s) in 33.1 s
{
  "actions": [
    "release_tag: set COLDLINE_RELEASE_TAG=3.1.1 and recreate api and worker (and the initializer they depend on) from the 3.1.1 images",
    "COLDLINE_RELEASE_TAG=3.1.1 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=1 api worker"
  ],
  "commit": "08f9b0129f1049caf1d8fa1fb12a0782df69a358",
  "compose_wait_seconds": 33.1,
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [
    {
      "desired": "3.1.1",
      "key": "release_tag",
      "observed": "3.1.0"
    }
  ],
  "first_probe": {
    "build_version": "3.1.1",
    "ready_status": 200
  },
  "mode": "reconcile",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "recorded_at": "2026-09-30T01:07:58+00:00"
}
```

The record reads the commit `08f9b0129f10`, finds exactly one difference on `release_tag`
(desired `3.1.1`, observed `3.1.0`), and applies it as one Compose command with
`--no-build --wait`, so the call returned only after the API readiness gate passed. Compose
waited 33.1 s, which covers the candidate's 20 s warm-up, and the first readiness probe was
`200` with `build_version` `3.1.1`.

Confirmed independently. `curl http://localhost:8000/version`:

```text
{"service":"coldline-api","build_version":"3.1.1","ready":true}
```

`docker compose --profile observability --profile localstack ps` (api and worker rows):

```text
NAME                                          IMAGE                   SERVICE   STATUS
ais-20260930-010448-501b2dac-api-1            coldline-api:3.1.1      api       Up 39 seconds (healthy)
ais-20260930-010448-501b2dac-worker-1         coldline-worker:3.1.1   worker    Up 39 seconds (healthy)
```

The version the running API answers is `3.1.1`, not just the tag I typed into the file, and
both first-party images carry the candidate tag.

## Step 2 - Catch and correct a change made by hand

The Compose command you ran by hand, the first `poe reconcile-check` output with every
difference it listed, the `poe reconcile` record, and the second `poe reconcile-check`
output reporting no drift. One sentence on what you intended to change versus what the
check found, and one on what a hand change the desired state does not describe would look
like to this check.

The command I ran by hand, with no commit and no `COLDLINE_RELEASE_TAG` in my shell:

```text
docker compose --profile observability --profile localstack up -d --no-build --scale worker=2 worker
```

Compose created `worker-2`, recreated `worker-1` and the initializer they depend on, and
reported every container started.

First `poe reconcile-check` after the hand change:

```text
Poe => python infra/gitops/reconcile.py check
commit 08f9b0129f10: drift on 2 key(s): release_tag, worker.replicas
{
  "commit": "08f9b0129f1049caf1d8fa1fb12a0782df69a358",
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [
    {
      "desired": "3.1.1",
      "key": "release_tag",
      "observed": "api=3.1.1, initializer=3.1.0, worker=3.1.0"
    },
    {
      "desired": 1,
      "key": "worker.replicas",
      "observed": 2
    }
  ],
  "drift": true,
  "mode": "check",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "api=3.1.1, initializer=3.1.0, worker=3.1.0",
    "worker.replicas": 2,
    "worker.restart_policy": "unless-stopped"
  },
  "probe": {
    "build_version": "3.1.1",
    "ready_status": 200
  },
  "recorded_at": "2026-09-30T01:08:58+00:00"
}
```

What I intended versus what the check found: I meant to add one worker, that is drift on
`worker.replicas` only, but the check found drift on two keys, because my plain Compose
command had no `COLDLINE_RELEASE_TAG` in the shell and so resolved the worker and
initializer images from `compose.yaml`'s default tag, silently rolling both back from
`3.1.1` to `3.1.0` while the API stayed at `3.1.1`. The stack was split across two releases
and nothing on my terminal said so — which is exactly the half-day Elena described.

`poe reconcile`, with no commit involved; HEAD still says one worker at `3.1.1`:

```text
Poe => python infra/gitops/reconcile.py apply
commit 08f9b0129f10: applied 2 difference(s) in 11.9 s
{
  "actions": [
    "release_tag: set COLDLINE_RELEASE_TAG=3.1.1 and recreate api and worker (and the initializer they depend on) from the 3.1.1 images",
    "worker.replicas: scale worker to 1 (--scale worker=1)",
    "COLDLINE_RELEASE_TAG=3.1.1 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=1 api worker"
  ],
  "commit": "08f9b0129f1049caf1d8fa1fb12a0782df69a358",
  "compose_wait_seconds": 11.9,
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [
    {
      "desired": "3.1.1",
      "key": "release_tag",
      "observed": "api=3.1.1, initializer=3.1.0, worker=3.1.0"
    },
    {
      "desired": 1,
      "key": "worker.replicas",
      "observed": 2
    }
  ],
  "first_probe": {
    "build_version": "3.1.1",
    "ready_status": 200
  },
  "mode": "reconcile",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "recorded_at": "2026-09-30T01:09:21+00:00"
}
```

Second `poe reconcile-check`:

```text
Poe => python infra/gitops/reconcile.py check
commit 08f9b0129f10: no drift
{
  "commit": "08f9b0129f1049caf1d8fa1fb12a0782df69a358",
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [],
  "drift": false,
  "mode": "check",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.1",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "probe": {
    "build_version": "3.1.1",
    "ready_status": 200
  },
  "recorded_at": "2026-09-30T01:09:30+00:00"
}
```

`docker compose --profile observability --profile localstack ps` afterwards shows one
worker again, back on the candidate image:

```text
NAME                                          IMAGE                   SERVICE   STATUS
ais-20260930-010448-501b2dac-api-1            coldline-api:3.1.1      api       Up 2 minutes (healthy)
ais-20260930-010448-501b2dac-worker-1         coldline-worker:3.1.1   worker    Up 25 seconds (healthy)
```

What this loop proves and what it does not. The committed state was never wrong here; the
running stack was, and the reconciler put it back without a new commit and without me
typing a second Compose command. But the check only compares the four keys the desired
state declares. A hand change to something the file does not describe — say an engineer
running `docker compose exec` to set an environment variable, editing a config mount, or
restarting one container with a different log level — would leave `differences` empty and
the check would report "no drift" while the stack was still not what anyone reviewed. This
loop catches release, replica count and restart policy; it is silent about everything else.

## Step 3 - Roll back with a revert

The revert commit's full SHA, `git log --oneline -3` showing the rollout and its revert,
the `poe reconcile` record (the difference on `release_tag` back to the known-good tag, the
wait, the first probe), and the `/version` output afterwards.

The revert commit, full SHA `af041c38c1e3a3d27fe02aa1e375d6854e261705`. I produced it with
`git revert 08f9b0129f1049caf1d8fa1fb12a0782df69a358` and kept git's generated subject and
its `This reverts commit 08f9b0129f1049caf1d8fa1fb12a0782df69a358.` line, adding only a
sentence saying why. I did not edit the tag back by hand.

`git log --oneline -3`, showing the rollout and its revert on the branch:

```text
af041c3 Revert "Roll out release 3.1.1 to api, worker and initializer"
08f9b01 Roll out release 3.1.1 to api, worker and initializer
f1ef17a Task 3.8 export refresh (source @ed9d0a9) (#6)
```

`poe reconcile` at the revert commit:

```text
Poe => python infra/gitops/reconcile.py apply
commit af041c38c1e3: applied 1 difference(s) in 12.5 s
{
  "actions": [
    "release_tag: set COLDLINE_RELEASE_TAG=3.1.0 and recreate api and worker (and the initializer they depend on) from the 3.1.0 images",
    "COLDLINE_RELEASE_TAG=3.1.0 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=1 api worker"
  ],
  "commit": "af041c38c1e3a3d27fe02aa1e375d6854e261705",
  "compose_wait_seconds": 12.5,
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "differences": [
    {
      "desired": "3.1.0",
      "key": "release_tag",
      "observed": "3.1.1"
    }
  ],
  "first_probe": {
    "build_version": "3.1.0",
    "ready_status": 200
  },
  "mode": "reconcile",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 1,
    "worker.restart_policy": "unless-stopped"
  },
  "recorded_at": "2026-09-30T01:10:51+00:00"
}
```

One difference on `release_tag`, from the observed `3.1.1` back to the committed `3.1.0`,
a first probe of `200` and a `build_version` of `3.1.0`. Compose waited 12.5 s against the
33.1 s of the rollout in Step 1: the known-good build has no 20 s warm-up, so the readiness
gate let the pass return sooner. Same file, same command, same reconciler path as the
rollout — on-call has one procedure, not two.

`curl http://localhost:8000/version` afterwards:

```text
{"service":"coldline-api","build_version":"3.1.0","ready":true}
```

## Step 4 - Set the restart policy and replica count by commit

The policy commit's full SHA and its diff, the `poe reconcile` record with its two
differences and the actions for each, the `docker compose ps` output listing every worker
container, the `docker inspect` restart policy of each, and the `poe reconcile-check` output
reporting no drift. Say which policy you chose for a worker that dies partway through a
summary during peak season, and why.

The policy commit, full SHA `f93a01b28d7070b215409a607d1c9b5e2d0c3246`. One commit carries
both changes:

```diff
diff --git a/deploy/desired-state.yaml b/deploy/desired-state.yaml
index 1c19977..ee4ce3e 100644
--- a/deploy/desired-state.yaml
+++ b/deploy/desired-state.yaml
@@ -32,7 +32,7 @@ api:
 
 worker:
   # Same four policies, same meaning, applied to every worker container.
-  restart_policy: unless-stopped
+  restart_policy: on-failure
   # How many worker containers Compose runs (`--scale worker=N`). Every replica consumes
   # the same SQS queue; a whole number of at least 1.
-  replicas: 1
+  replicas: 2
```

Which policy, and why. I chose `on-failure` for the worker. A worker that dies partway
through a summary exits with a non-zero code, and `on-failure` brings it straight back, so
the clinic waiting on that summary does not wait for a person to notice. A clean exit,
code 0, is not a crash: it is a deliberate drain or shutdown, and `on-failure` leaves it
exited rather than restarting it into a queue we are trying to quiesce. `always` and
`unless-stopped` would both fight that drain; `"no"` would leave a crashed worker down
until on-call noticed, which is the outcome Elena is complaining about. The API keeps
`unless-stopped`, unchanged.

`poe reconcile` at the policy commit, two differences and one action for each:

```text
Poe => python infra/gitops/reconcile.py apply
commit f93a01b28d70: applied 2 difference(s) in 12.4 s
{
  "actions": [
    "worker.restart_policy: write restart on-failure into deploy/.reconcile-override.yaml and recreate worker with it",
    "worker.replicas: scale worker to 2 (--scale worker=2)",
    "COLDLINE_RELEASE_TAG=3.1.0 docker compose --profile observability --profile localstack -f compose.yaml -f deploy/.reconcile-override.yaml up --detach --no-build --wait --scale worker=2 api worker"
  ],
  "commit": "f93a01b28d7070b215409a607d1c9b5e2d0c3246",
  "compose_wait_seconds": 12.4,
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 2,
    "worker.restart_policy": "on-failure"
  },
  "differences": [
    {
      "desired": "on-failure",
      "key": "worker.restart_policy",
      "observed": "unless-stopped"
    },
    {
      "desired": 2,
      "key": "worker.replicas",
      "observed": 1
    }
  ],
  "first_probe": {
    "build_version": "3.1.0",
    "ready_status": 200
  },
  "mode": "reconcile",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 2,
    "worker.restart_policy": "on-failure"
  },
  "recorded_at": "2026-09-30T01:12:06+00:00"
}
```

`docker compose --profile observability --profile localstack ps`, two worker containers:

```text
NAME                                          IMAGE                   SERVICE   STATUS
ais-20260930-010448-501b2dac-api-1            coldline-api:3.1.0      api       Up About a minute (healthy)
ais-20260930-010448-501b2dac-worker-1         coldline-worker:3.1.0   worker    Up 17 seconds (healthy)
ais-20260930-010448-501b2dac-worker-2         coldline-worker:3.1.0   worker    Up 17 seconds (healthy)
```

The restart policy each one actually carries, from the container ids that
`docker compose --profile observability --profile localstack ps -q worker` returned and
`docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' <id>`:

```text
c74368846cf4198e2428c28327aae68de34d15f3a220aeac814f74920fe7499a /ais-20260930-010448-501b2dac-worker-1 on-failure
531832e660da0cb65f34fc53c0dcdd24cec4839b756bb1b36ef310906465a823 /ais-20260930-010448-501b2dac-worker-2 on-failure

api container restart policy, for comparison:
4a1b4a33d0a2c7027f4b75feb501ad8380e7e628e33f14df56c92a6337d35f8e /ais-20260930-010448-501b2dac-api-1 unless-stopped
```

Docker reports `on-failure` on both workers and `unless-stopped` on the API, which is what
the file commits for each.

`poe reconcile-check` with HEAD at the policy commit:

```text
Poe => python infra/gitops/reconcile.py check
commit f93a01b28d70: no drift
{
  "commit": "f93a01b28d7070b215409a607d1c9b5e2d0c3246",
  "desired": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 2,
    "worker.restart_policy": "on-failure"
  },
  "differences": [],
  "drift": false,
  "mode": "check",
  "observed": {
    "api.restart_policy": "unless-stopped",
    "release_tag": "3.1.0",
    "worker.replicas": 2,
    "worker.restart_policy": "on-failure"
  },
  "probe": {
    "build_version": "3.1.0",
    "ready_status": 200
  },
  "recorded_at": "2026-09-30T01:12:37+00:00"
}
```

In Step 2 a second worker was drift and the reconciler removed it. Here the same second
worker is the desired state and the reconciler creates it. The running stack looks the
same in both cases; what differs is that this one has an author, a diff and a reviewer.
