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

Run the publisher against a full 40-character commit SHA:

```bash
python scripts/publish_worker_bundle.py <commit-sha>
```

The command validates that GitHub resolves the requested commit, downloads the
archive for that exact SHA, enforces a 512 MiB maximum, calculates SHA-256, and
uploads it to an immutable key:

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
On the trusted API host, call
`build_worker_start_command(api_url, bootstrap_token)` from
`musicmaster.cloud.autodl_pro`, then pass the returned string as the
`start_command` argument to `AutoDLProClient.create_instance(...)` (or
`power_on(...)`). The builder embeds a compressed copy of the small
`scripts/bootstrap_worker_bundle.py` helper directly in the startup command.
The instance writes that helper to a temporary file, runs it, and downloads
the complete pinned source archive. The verified archive then supplies the
normal worker launcher and all application code.

The startup command carries only the short-lived, single-use
`MUSICMASTER_BOOTSTRAP_TOKEN`; it never embeds a GitHub token or long-lived
worker token. Because the startup command is sent to AutoDL as instance
configuration, create a short-expiry bootstrap token immediately before
starting the instance and treat the provider's command/configuration history
as sensitive until that token has been consumed or expired. The builder
validates the API URL and token length; it does not issue the bootstrap token
or provision an instance by itself.

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

This implements the worker-side source download and verification. It does not
provision or power on AutoDL instances, create bootstrap tokens, publish the
bundle automatically, configure Render secrets, or shut instances down. The
dispatcher must verify AutoDL has powered off before releasing a paid instance.
No paid GPU should be started for CI or bootstrap unit tests.
