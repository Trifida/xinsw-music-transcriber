# -*- coding: utf-8 -*-
import io
import tarfile
from pathlib import Path

import pytest

from scripts import bootstrap_worker_bundle as bootstrap


def _archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name, kind, payload in entries:
            info = tarfile.TarInfo(name)
            if kind == "dir":
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                tar.addfile(info)
            else:
                data = payload
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def test_safe_extract_accepts_single_root_with_worker_entrypoint(tmp_path):
    archive_path = tmp_path / "bundle.tar.gz"
    archive_path.write_bytes(_archive([
        ("repo", "dir", b""),
        ("repo/musicmaster", "dir", b""),
        ("repo/musicmaster/cloud", "dir", b""),
        ("repo/musicmaster/cloud/worker.py", "file", b"print('worker')"),
    ]))
    root = bootstrap._safe_extract(archive_path, tmp_path / "extract")
    assert root == tmp_path / "extract" / "repo"
    assert (root / "musicmaster/cloud/worker.py").read_text() == "print('worker')"


def test_safe_extract_rejects_parent_traversal(tmp_path):
    archive_path = tmp_path / "unsafe.tar.gz"
    archive_path.write_bytes(_archive([
        ("repo/../../outside.txt", "file", b"no"),
    ]))
    with pytest.raises(RuntimeError, match="unsafe path"):
        bootstrap._safe_extract(archive_path, tmp_path / "extract")
    assert not (tmp_path / "outside.txt").exists()


def test_safe_extract_rejects_symlinks(tmp_path):
    archive_path = tmp_path / "link.tar.gz"
    archive_path.write_bytes(_archive([
        ("repo", "dir", b""),
        ("repo/escape", "symlink", "../../outside"),
    ]))
    with pytest.raises(RuntimeError, match="link or special"):
        bootstrap._safe_extract(archive_path, tmp_path / "extract")


def test_safe_extract_requires_worker_entrypoint(tmp_path):
    archive_path = tmp_path / "incomplete.tar.gz"
    archive_path.write_bytes(_archive([
        ("repo", "dir", b""),
        ("repo/README.md", "file", b"not a worker"),
    ]))
    with pytest.raises(RuntimeError, match="missing the cloud worker"):
        bootstrap._safe_extract(archive_path, tmp_path / "extract")


def test_https_url_rejects_plain_http_and_embedded_credentials():
    with pytest.raises(RuntimeError, match="HTTPS"):
        bootstrap._https_url("http://example.test/bundle", "Bundle URL")
    with pytest.raises(RuntimeError, match="HTTPS"):
        bootstrap._https_url("https://user:pass@example.test/bundle", "Bundle URL")
    assert bootstrap._https_url("https://storage.example.test/bundle", "Bundle URL")



def test_bootstrap_exchanges_token_downloads_verified_bundle_and_returns_runtime_env(
    tmp_path, monkeypatch
):
    import hashlib

    commit = "a" * 40
    archive_bytes = _archive([
        ("repo", "dir", b""),
        ("repo/musicmaster", "dir", b""),
        ("repo/musicmaster/cloud", "dir", b""),
        ("repo/musicmaster/cloud/worker.py", "file", b"worker"),
        ("repo/scripts", "dir", b""),
        ("repo/scripts/run_autodl_cloud_worker.sh", "file", b"#!/bin/sh"),
    ])
    digest = hashlib.sha256(archive_bytes).hexdigest()
    calls = []

    def fake_request_json(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/api/internal/bootstrap"):
            return {
                "worker_token": "exchanged-worker-token",
                "worker_id": "gpu-worker-1",
                "instance_uuid": "pro-instance-1",
            }
        return {
            "repository_commit": commit,
            "sha256": digest,
            "object_key": f"worker-bundles/{commit}/{digest}.tar.gz",
            "url": "https://storage.example.test/presigned-bundle",
        }

    def fake_download(url, destination):
        destination.write_bytes(archive_bytes)
        return digest

    monkeypatch.setattr(bootstrap, "_request_json", fake_request_json)
    monkeypatch.setattr(bootstrap, "_download", fake_download)
    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example.test")
    monkeypatch.setenv("MUSICMASTER_BOOTSTRAP_TOKEN", "b" * 40)
    monkeypatch.delenv("MUSICMASTER_WORKER_TOKEN", raising=False)
    monkeypatch.setenv("MUSICMASTER_WORKER_BUNDLE_HOME", str(tmp_path / "bundles"))

    result = bootstrap.bootstrap()

    assert result["bundle_root"] == str(tmp_path / "bundles" / commit)
    assert result["worker_token"] == "exchanged-worker-token"
    assert result["worker_id"] == "gpu-worker-1"
    assert result["instance_uuid"] == "pro-instance-1"
    assert (Path(result["bundle_root"]) / "musicmaster/cloud/worker.py").is_file()
    assert calls[0][0].endswith("/api/internal/bootstrap")
    assert calls[1][0].endswith("/api/internal/worker/bundle")
    assert calls[1][1]["token"] == "exchanged-worker-token"
