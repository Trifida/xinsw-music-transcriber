from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from scripts import run_colab_cloud_worker as launcher


class Response:
    def __init__(self, body: bytes):
        self.body = io.BytesIO(body)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.body.read(size)


def _archive() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        files = {
            "repo-commit/musicmaster/cloud/worker.py": b"# worker\n",
            "repo-commit/scripts/run_colab_cloud_worker.py": b"# launcher\n",
        }
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(body))
    return output.getvalue()


def test_colab_launcher_downloads_and_verifies_pinned_source_bundle(monkeypatch, tmp_path):
    archive = _archive()
    digest = hashlib.sha256(archive).hexdigest()
    commit = "a" * 40
    manifest = {
        "repository_commit": commit,
        "sha256": digest,
        "url": "https://signed.example/worker.tar.gz",
    }
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        if request.full_url.endswith("/api/internal/worker/bundle"):
            return Response(json.dumps(manifest).encode())
        if request.full_url == manifest["url"]:
            return Response(archive)
        raise AssertionError(request.full_url)

    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example")
    monkeypatch.setenv("MUSICMASTER_WORKER_TOKEN", "worker-secret")
    monkeypatch.delenv("MUSICMASTER_SOURCE_BUNDLE_ACTIVE", raising=False)
    monkeypatch.setattr(launcher, "BUNDLE_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        "musicmaster.cloud.worker._config",
        lambda: ("https://api.example", "worker-secret", "colab-t4", None),
    )
    executed = {}
    monkeypatch.setattr(
        launcher.os, "execve",
        lambda executable, argv, env: executed.update(
            executable=executable, argv=argv, env=env
        ),
    )

    launcher._activate_published_source_bundle()

    bundle_root = tmp_path / "cache" / commit
    assert (bundle_root / "musicmaster/cloud/worker.py").read_bytes() == b"# worker\n"
    assert (bundle_root / ".xinsw-bundle-sha256").read_text() == digest
    assert executed["argv"][1] == str(bundle_root / "scripts/run_colab_cloud_worker.py")
    assert executed["env"]["MUSICMASTER_SOURCE_BUNDLE_ACTIVE"] == commit
    assert calls[0][0].endswith("/api/internal/worker/bundle")
    assert calls[1][0] == manifest["url"]


def test_colab_launcher_rejects_source_bundle_checksum_mismatch(monkeypatch, tmp_path):
    archive = _archive()
    manifest = {
        "repository_commit": "b" * 40,
        "sha256": "0" * 64,
        "url": "https://signed.example/worker.tar.gz",
    }

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/internal/worker/bundle"):
            return Response(json.dumps(manifest).encode())
        return Response(archive)

    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example")
    monkeypatch.setenv("MUSICMASTER_WORKER_TOKEN", "worker-secret")
    monkeypatch.delenv("MUSICMASTER_SOURCE_BUNDLE_ACTIVE", raising=False)
    monkeypatch.setattr(launcher, "BUNDLE_CACHE_ROOT", tmp_path / "cache")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        "musicmaster.cloud.worker._config",
        lambda: ("https://api.example", "worker-secret", "colab-t4", None),
    )

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        launcher._activate_published_source_bundle()
