# Private GPU worker source bundle

The GPU node must never receive a GitHub token. The trusted API host publishes a
pinned private-repository archive into the private object-storage bucket; a
worker receives only a short-lived presigned download URL.

## Publish from the trusted API host

Configure these secrets on the API host (for example, Render):

- `MUSICMASTER_GITHUB_READ_TOKEN`: fine-grained GitHub token with read-only
  Contents access to this private repository.
- `MUSICMASTER_GITHUB_REPOSITORY`: `Trifida/xinsw-music-transcriber`.
- The normal private object-storage settings already used by `S3ObjectStore`.

The API host also exposes a worker-authenticated publish endpoint, so an
operator does not need shell access to the Render container:

```http
POST /api/internal/worker/bundle/publish
Authorization: Bearer <MUSICMASTER_WORKER_TOKEN>
Content-Type: application/json

{"commit_sha":"<full-40-character-commit-sha>"}
```

The endpoint runs the same publisher on the trusted API host and returns the
published manifest. The GitHub read token and S3 credentials never leave Render.
The existing command-line publisher remains available for controlled host-side
operations:

```bash
python scripts/publish_worker_bundle.py <commit-sha>
```

The publisher validates that GitHub resolves the requested commit, downloads
the archive for that exact SHA, enforces a 512 MiB maximum, calculates SHA-256,
and uploads it to an immutable key:

```
worker-bundles/<commit-sha>/<sha256>.tar.gz
```

It prints a JSON manifest containing the commit, object key, checksum, and size.
Do not paste the GitHub token into a command argument or commit it to the repo.

## Configure worker bundle delivery

After publishing, set these API-host environment variables from the publisher
output:

- `MUSICMASTER_WORKER_BUNDLE_COMMIT`
- `MUSICMASTER_WORKER_BUNDLE_SHA256`
- `MUSICMASTER_WORKER_BUNDLE_KEY`

The authenticated endpoint
`GET /api/internal/worker/bundle` returns the pinned manifest and a
10-minute presigned download URL. It requires the worker bearer credential.
The endpoint refuses incomplete values, malformed hashes, and object keys that
do not match the configured commit and checksum.

## AutoDL bootstrap sequence

A fresh AutoDL image does **not** need a preinstalled repository checkout.
On the trusted API host, the manual provisioning endpoint invokes
`create_autodl_worker(...)` from `musicmaster.cloud.dispatcher`. The orchestration
uses `build_worker_start_command(api_url, bootstrap_token)` internally. The
builder embeds a compressed copy of the small
`scripts/bootstrap_worker_bundle.py` helper directly in the startup command.
The instance writes that helper to a temporary file, runs it, and downloads
the complete pinned source archive. The verified archive then supplies the
normal worker launcher and all application code.

The startup command carries only the short-lived, single-use
`MUSICMASTER_BOOTSTRAP_TOKEN`; it never embeds a GitHub token or long-lived
worker token. Calling the manual endpoint can incur GPU charges, so keep the
dispatcher credential private and do not expose this route to the public UI.
Because the startup command is sent to AutoDL as instance configuration, the
one-time token remains sensitive until consumed or expired. The dispatcher
creates the worker row, stores only a SHA-256 token hash, creates the instance
without a startup command, persists the instance ID, and only then powers it
on with the generated command. This ordering prevents a fast boot from
consuming the token before the instance ID has been attached to its database
record.

The bootstrap helper performs these steps before installing model dependencies:

1. Exchange the single-use `MUSICMASTER_BOOTSTRAP_TOKEN` for a worker token.
2. Request the pinned bundle manifest using that worker token.
3. Download the archive over HTTPS into a temporary directory.
4. Verify the complete archive SHA-256 against the API manifest.
5. Reject absolute/traversal paths, symlinks, hard links, and special files.
6. Extract into a version-specific directory under
   `~/.cache/xinsw-worker-bundles/<commit-sha>`.
7. Execute the worker launcher from that verified source directory.

The short-lived bootstrap token is removed from the process environment after
exchange. The worker token is held only in the running process environment and
is not written to the bundle or a persistent credentials file. Set
`MUSICMASTER_WORKER_BUNDLE_HOME` only when the default user cache is unsuitable.

The embedded helper is only a carrier for the download operation. All application
code and worker dependencies are taken from the checksum-verified commit bundle.

## Remaining deployment boundary

The provisioning helper is exposed through a manual endpoint
`POST /api/internal/dispatcher/workers`, protected by a separate
`MUSICMASTER_DISPATCHER_TOKEN` (minimum 32 characters). Configure
`MUSICMASTER_API_URL`, `MUSICMASTER_AUTODL_IMAGE_UUID`,
`MUSICMASTER_AUTODL_CUDA_V_FROM`, and `AUTODL_PRO_TOKEN` only on the trusted
API host. The endpoint provisions exactly one worker per authorized request.
It is **not** called automatically by queue uploads or a polling loop; queue
capacity decisions remain a separate future task. It does not publish the
bundle automatically, configure Render secrets, monitor the instance through
the full job lifecycle, shut instances down, or release them. The dispatcher
must verify AutoDL has powered off before releasing a paid instance. No paid
GPU should be started for CI or bootstrap unit tests.


## Dispatcher concurrency and GPU capacity gate

The manual provisioning endpoint runs through
`PostgresJobStore.run_with_dispatch_capacity(max_workers, operation)`.
It acquires a transaction-scoped PostgreSQL advisory lock using
`pg_try_advisory_xact_lock`, counts workers in `starting`, `idle`, `busy`,
`stopping`, or `error` (including error rows without a known instance ID),
and rejects provisioning if another dispatcher is active or
the configured capacity is full. The lock remains held until the AutoDL
create/persist/power-on operation returns. Configure
`MUSICMASTER_AUTODL_MAX_WORKERS` to an integer from 1 through 10; the default
is 1. No new table or migration is required. Stale active worker rows
intentionally consume capacity until lifecycle reconciliation is implemented,
which favors avoiding duplicate paid instances over automatic recovery.


## Worker idle shutdown and AutoDL release

The API exposes a manual, dispatcher-authenticated reconciliation endpoint:
`POST /api/internal/dispatcher/workers/{worker_id}/reconcile`.

- Configure `MUSICMASTER_AUTODL_IDLE_SECONDS` (60–86400; default 300).
- Only a worker whose DB state is `idle`, whose `active_job_id` is NULL, and whose last heartbeat is older than the threshold can atomically transition to `stopping`.
- The worker's heartbeat API now accepts only `idle` or `busy`; it cannot revive a worker already stopping/stopped. Job claiming and re-registration are also blocked once shutdown starts.
- The reconciler queries AutoDL status. If `running`, it requests power-off and leaves the DB state at `stopping`. A later reconciliation must query again.
- It calls release only when the provider status is explicitly `shutdown` or `stopped`; unknown/transitional states are non-destructive and remain `stopping`.
- The DB changes to `stopped` only after the release API returns success.
- This endpoint is manual-only; no background scheduler calls it yet. Do not expose the dispatcher token to the browser. Calls can power off/release paid instances.
- Provider release and Postgres cannot participate in one atomic transaction. If the provider release succeeds but the API process dies before recording `stopped`, operator reconciliation may be required; automatic "not found means released" inference is intentionally not implemented.


## Recovery after an interrupted provider release

AutoDL Pro exposes a paginated instance-list endpoint. The reconciler now uses
that endpoint only when an instance status lookup fails (for example, after a
release succeeded but the API process stopped before updating Postgres). It
scans every page advertised by the provider response and treats a missing
instance as released only after the listing is complete and structurally valid.
If the instance is still listed, or listing is incomplete/unavailable, the DB
row remains `stopping`; no second release is attempted based on uncertainty.
This is a recovery check, not a scheduler. The instance-list API contract is
documented by AutoDL at https://autodl.com/docs/instance_pro_api/.

An empty but valid provider listing (`max_page: 0` and an empty `list`) is
also accepted as a complete scan; zero pages with any returned records is
rejected as inconsistent.


## Bounded idle-worker sweep (manual only)

The dispatcher now exposes
`POST /api/internal/dispatcher/workers/reconcile-idle`. Its request defaults
to `dry_run: true` and a maximum batch size of 10 (hard cap 25). Dry-run only
queries stale, truly idle workers and returns candidate IDs/timestamps; it does
not construct an AutoDL client or change provider/DB state. Set
`dry_run: false` explicitly to reconcile that bounded batch sequentially.
Each worker result is reported independently, and provider error messages are
not returned. This endpoint is still dispatcher-authenticated and manual-only;
no cron job, queue event, or automatic scheduler invokes it.


## Failed-worker resource accounting and recovery

A worker marked `error` can still have a linked AutoDL instance (for example,
instance creation succeeded but power-on or bootstrap registration failed).
Such rows now continue to consume dispatcher capacity while
`instance_uuid IS NOT NULL`. The read-only stale-worker candidate query includes
both `idle` and `error` states, but only with no active job and a linked
instance. The same atomic transition moves an old `error` worker to
`stopping` only after the configured idle threshold. Fresh errors are left
untouched. Provider shutdown and release remain governed by the existing
status-confirmation rules.

### Unresolved provisioning errors reserve capacity

The capacity query counts **all** worker rows in `starting`, `idle`, `busy`, `stopping`, or `error`, including error rows with no linked AutoDL instance ID. This is intentionally conservative: the AutoDL create request may have succeeded remotely while its response was lost or timed out before the instance ID could be persisted. Such a row is an unresolved provisioning intent and must not silently free a slot for another paid create request. Resolve it through operator investigation before retrying provisioning.



## Recovery after an ambiguous AutoDL create timeout

Every newly provisioned worker receives a deterministic, compact AutoDL
`instance_name` label derived from its worker ID (`XW-<24 hex characters>`).
If the create request times out after AutoDL may have accepted it but before
the API host receives/persists the instance UUID, the worker remains in
`error` and continues to reserve capacity.

A dispatcher-authenticated, manual recovery endpoint is available:

`POST /api/internal/dispatcher/workers/{worker_id}/recover-instance`

It only accepts an `error` worker with no linked instance and no active job.
It scans the complete paginated AutoDL instance list and compares the exact
provider `name` label:

- Exactly one match: link that UUID to the worker and its bootstrap-token row.
  This is a database-only operation; it does not power on, power off, or
  release the provider instance.
- No match: leave the worker unchanged and return `retry_safe: false`.
  AutoDL listing may lag a create request, so absence from one complete scan
  is not proof that retrying creation is safe. Wait and check again.
- More than one match: leave the worker unchanged and report ambiguity. Never
  guess which paid instance belongs to the worker.
- Incomplete, malformed, or unavailable pagination: fail closed; do not link
  an instance or clear the capacity reservation.

This deterministic label is applied only to newly created workers. Older
ambiguous error rows that were created with the former generic instance name
cannot be automatically matched by this mechanism and require manual
investigation in the AutoDL console. The endpoint is not called automatically
and performs no provider mutation.

### Manual provisioning idempotency

- `POST /api/internal/dispatcher/workers` requires an `Idempotency-Key` header (16–128 printable ASCII characters).
- The API hashes the key into a deterministic `dispatch-<sha256>` worker ID. The raw key is not stored or returned.
- A repeated request with the same key returns the existing worker record and never constructs an AutoDL client or calls create/power-on again.
- An existing unresolved `error` worker is returned as-is with `retry_safe: false`; operators must use the manual instance-recovery flow. A new key is not a safe way to retry an ambiguous create.
- Use a new idempotency key only when intentionally requesting a distinct worker after reviewing the prior worker and capacity state.
- The database schema is unchanged; the existing unique worker ID is the durable idempotency record.
