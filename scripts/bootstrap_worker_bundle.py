#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch, verify, and safely install the pinned private GPU worker bundle."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

MAX_BUNDLE_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 100_000


def _https_url(value: str, label: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(f"{label} must be a valid HTTPS URL.")
    return value


def _request_json(url: str, *, token: str | None = None, method: str = "GET",
                  payload: dict | None = None) -> dict:
    headers = {"Accept": "application/json", "User-Agent": "XinsW-Music-Bootstrap/1"}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(_https_url(url, "API URL"), data=body,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read(1024 * 1024).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, UnicodeDecodeError,
            json.JSONDecodeError) as exc:
        raise RuntimeError(f"Bootstrap API request failed: {type(exc).__name__}") from None
    if not isinstance(result, dict):
        raise RuntimeError("Bootstrap API returned an invalid response.")
    return result


def _download(url: str, destination: Path) -> str:
    request = urllib.request.Request(_https_url(url, "Bundle URL"),
                                    headers={"User-Agent": "XinsW-Music-Bootstrap/1"})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=1800) as response, destination.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BUNDLE_BYTES:
                    raise RuntimeError("Worker source bundle exceeds the 512 MiB limit.")
                digest.update(chunk)
                out.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Worker source download failed: {type(exc).__name__}") from None
    if total == 0:
        raise RuntimeError("Worker source bundle is empty.")
    return digest.hexdigest()


def _safe_extract(archive_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_MEMBERS:
                raise RuntimeError("Worker source archive has an invalid member count.")
            top_levels: set[str] = set()
            for member in members:
                name = PurePosixPath(member.name)
                if name.is_absolute() or not name.parts or any(p in {"", ".", ".."} for p in name.parts):
                    raise RuntimeError("Worker source archive contains an unsafe path.")
                top_levels.add(name.parts[0])
                if not (member.isdir() or member.isfile()):
                    raise RuntimeError("Worker source archive contains a link or special file.")
                target = (destination / Path(*name.parts)).resolve()
                try:
                    target.relative_to(destination.resolve())
                except ValueError:
                    raise RuntimeError("Worker source archive path escapes its destination.") from None
            if len(top_levels) != 1:
                raise RuntimeError("Worker source archive must contain one repository root.")
            archive.extractall(destination, members=members)
            root = destination / next(iter(top_levels))
            if not root.is_dir() or not (root / "musicmaster" / "cloud" / "worker.py").is_file():
                raise RuntimeError("Worker source archive is missing the cloud worker entry point.")
            return root
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError(f"Worker source archive is invalid: {type(exc).__name__}") from None


def bootstrap() -> dict:
    base = os.environ.get("MUSICMASTER_API_URL", "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("MUSICMASTER_API_URL must be an HTTPS URL.")
    token = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    bootstrap_token = os.environ.get("MUSICMASTER_BOOTSTRAP_TOKEN", "").strip()
    if not token:
        if len(bootstrap_token) < 32:
            raise RuntimeError("A valid MUSICMASTER_BOOTSTRAP_TOKEN is required.")
        exchanged = _request_json(base + "/api/internal/bootstrap", method="POST",
                                  payload={"bootstrap_token": bootstrap_token})
        token = str(exchanged.get("worker_token") or "").strip()
        if not token:
            raise RuntimeError("Bootstrap exchange did not return a worker credential.")
        os.environ["MUSICMASTER_WORKER_TOKEN"] = token
        os.environ["MUSICMASTER_WORKER_ID"] = str(exchanged.get("worker_id") or "").strip()
        instance_uuid = exchanged.get("instance_uuid")
        if instance_uuid:
            os.environ["MUSICMASTER_INSTANCE_UUID"] = str(instance_uuid)

    manifest = _request_json(base + "/api/internal/worker/bundle", token=token)
    commit = str(manifest.get("repository_commit") or "").lower()
    digest_expected = str(manifest.get("sha256") or "").lower()
    object_key = str(manifest.get("object_key") or "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise RuntimeError("Worker bundle manifest has an invalid commit SHA.")
    if len(digest_expected) != 64 or any(c not in "0123456789abcdef" for c in digest_expected):
        raise RuntimeError("Worker bundle manifest has an invalid SHA-256.")
    if object_key != f"worker-bundles/{commit}/{digest_expected}.tar.gz":
        raise RuntimeError("Worker bundle manifest object key does not match its digest.")
    bundle_url = _https_url(str(manifest.get("url") or ""), "Bundle URL")

    root = Path(os.environ.get("MUSICMASTER_WORKER_BUNDLE_HOME", str(Path.home() / ".cache" / "xinsw-worker-bundles"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    final_dir = root / commit
    marker = final_dir / ".xinsw-bundle-sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == digest_expected:
        return {"bundle_root": str(final_dir), "commit": commit, "worker_token": token, "worker_id": os.environ.get("MUSICMASTER_WORKER_ID", ""), "instance_uuid": os.environ.get("MUSICMASTER_INSTANCE_UUID", "")}

    with tempfile.TemporaryDirectory(prefix=".xinsw-bootstrap-", dir=root) as temp:
        temp_root = Path(temp)
        archive_path = temp_root / "source.tar.gz"
        actual_digest = _download(bundle_url, archive_path)
        if actual_digest != digest_expected:
            raise RuntimeError("Worker source bundle SHA-256 verification failed.")
        extracted_parent = temp_root / "extract"
        source_root = _safe_extract(archive_path, extracted_parent)
        staged = temp_root / "installed"
        shutil.copytree(source_root, staged)
        (staged / ".xinsw-bundle-sha256").write_text(digest_expected + "\n", encoding="ascii")
        if final_dir.exists():
            raise RuntimeError("A different or incomplete bundle already exists for this commit.")
        os.replace(staged, final_dir)
    return {"bundle_root": str(final_dir), "commit": commit}


if __name__ == "__main__":
    try:
        print(json.dumps(bootstrap(), separators=(",", ":")))
    except Exception as exc:
        print(f"[cloud-bootstrap] failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
