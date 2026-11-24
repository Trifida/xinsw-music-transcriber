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

## Current boundary

This change implements the trusted-host publisher and authenticated URL
issuance. It does not yet install the archive on AutoDL, provision instances,
or shut instances down. Those lifecycle steps remain deliberately separate:
the GPU bootstrap must verify the SHA-256 before extraction, and the dispatcher
must verify AutoDL has powered off before releasing a paid instance.
