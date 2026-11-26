# CPU Worker Container

The cloud worker image is separate from the website/API image. Keep the existing
root `Dockerfile` unchanged; build this worker with `Dockerfile.worker`.

## Runtime layout

- `/opt/xinsw-core-venv`: TensorFlow 2.15, CREPE, transcription and score rendering.
- `/opt/xinsw-sep-venv`: CPU-only PyTorch and audio-separator.
- `/models/audio-separator`: audio-separator model cache. Mount persistent storage here
  if the worker host supports it; otherwise models are downloaded again after a fresh container.
- `/tmp/xinsw-worker`: per-job temporary working files.

The worker process runs from the core environment. The existing runner starts
`musicmaster.separate.pipeline` with `MUSICMASTER_SEP_PYTHON`, so the separator
environment does not install the MusicMaster project.

## Required runtime configuration

Inject these values through the container platform's secret/environment settings:

- `MUSICMASTER_API_URL`: HTTPS root URL of the website/API.
- `MUSICMASTER_WORKER_TOKEN`: worker credential; alternatively use the existing
  short-lived `MUSICMASTER_BOOTSTRAP_TOKEN` flow.

Optional values:

- `MUSICMASTER_WORKER_ID`: stable worker identifier (defaults to the container hostname).
- `MUSICMASTER_INSTANCE_UUID`: provider instance identifier.
- `MUSICMASTER_WORKER_POLL_SECONDS`: queue poll interval (defaults to 5 seconds).
- `MUSICMASTER_SEP_MODELS`: separator model cache path (defaults to
  `/models/audio-separator`).
- `MUSICMASTER_WORKER_DATA`: temporary work root (defaults to `/tmp/xinsw-worker`).

No API token, database credential, object-storage credential, or model weights are
baked into the image. The worker obtains job and artifact URLs from the existing API.

## Build and publish

The GitHub Actions workflow `.github/workflows/build-worker-image.yml` builds on
the development branch. Pull requests build without publishing. Pushes publish
versioned SHA and `dev` tags to:

`ghcr.io/trifida/xinsw-music-transcriber-worker`

The package is initially private under GitHub Container Registry defaults.
Do not change package visibility or deploy this image to Render as the website service.

## CPU behavior

This image is intentionally CPU-only for reproducible validation. It does not
request, create, or provision a GPU. A GPU-specific image should be a separate
future build variant with its own tested dependency lock.
