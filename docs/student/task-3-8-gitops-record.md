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

_Write your evidence here._

## Step 2 - Catch and correct a change made by hand

The Compose command you ran by hand, the first `poe reconcile-check` output with every
difference it listed, the `poe reconcile` record, and the second `poe reconcile-check`
output reporting no drift. One sentence on what you intended to change versus what the
check found, and one on what a hand change the desired state does not describe would look
like to this check.

_Write your evidence here._

## Step 3 - Roll back with a revert

The revert commit's full SHA, `git log --oneline -3` showing the rollout and its revert,
the `poe reconcile` record (the difference on `release_tag` back to the known-good tag, the
wait, the first probe), and the `/version` output afterwards.

_Write your evidence here._

## Step 4 - Set the restart policy and replica count by commit

The policy commit's full SHA and its diff, the `poe reconcile` record with its two
differences and the actions for each, the `docker compose ps` output listing every worker
container, the `docker inspect` restart policy of each, and the `poe reconcile-check` output
reporting no drift. Say which policy you chose for a worker that dies partway through a
summary during peak season, and why.

_Write your evidence here._
