# -*- coding: utf-8 -*-
"""Publish immutable GitHub source archives to private object storage.

The GitHub read token is used only by the publishing process on the API host.
GPU workers receive only a short-lived object-storage download URL.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from musicmaster.cloud.object_store import S3ObjectStore


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
DEFAULT_MAX_BUNDLE_BYTES = 512 * 1024 * 1024


class SourceBundleError(RuntimeError):
    """A source archive could not be safely fetched or published."""


@dataclass(frozen=True)
class PublishedBundle:
    repository: str
    commit_sha: str
    object_key: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubSourceBundlePublisher:
    """Fetch a pinned private-repository archive and publish it immutably."""

    API_BASE = "https://api.github.com"

    def __init__(
        self,
        objects: S3ObjectStore | None = None,
        *,
        token: str | None = None,
        repository: str | None = None,
        max_bytes: int = DEFAULT_MAX_BUNDLE_BYTES,
        timeout: int = 90,
    ) -> None:
        self.token = (token or os.environ.get("MUSICMASTER_GITHUB_READ_TOKEN", "")).strip()
        self.repository = (
            repository or os.environ.get("MUSICMASTER_GITHUB_REPOSITORY", "")
        ).strip()
        if not self.token:
            raise ValueError("MUSICMASTER_GITHUB_READ_TOKEN is required.")
        if not _REPO_RE.fullmatch(self.repository):
            raise ValueError("MUSICMASTER_GITHUB_REPOSITORY must be owner/repository.")
        self.max_bytes = int(max_bytes)
        self.timeout = int(timeout)
        if self.max_bytes <= 0 or self.timeout <= 0:
            raise ValueError("max_bytes and timeout must be positive.")
        self.objects = objects or S3ObjectStore()

    def _request(self, url: str, *, accept: str) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "XinsW-Music-Source-Bundle/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(1024 * 1024, self.max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise SourceBundleError(
                            f"GitHub source archive exceeds {self.max_bytes} bytes."
                        )
                    chunks.append(chunk)
                return b"".join(chunks)
        except SourceBundleError:
            raise
        except urllib.error.HTTPError as exc:
            # Do not include response bodies: private-repository errors may echo
            # request details and the token must never reach logs.
            raise SourceBundleError(f"GitHub archive request failed (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceBundleError(
                f"GitHub archive request failed ({type(exc).__name__})."
            ) from None

    def publish(self, commit_sha: str) -> PublishedBundle:
        sha = str(commit_sha or "").strip().lower()
        if not _SHA_RE.fullmatch(sha):
            raise ValueError("commit_sha must be a full 40-character Git commit SHA.")

        metadata_raw = self._request(
            f"{self.API_BASE}/repos/{self.repository}/commits/{sha}",
            accept="application/vnd.github+json",
        )
        try:
            metadata = json.loads(metadata_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SourceBundleError("GitHub returned invalid commit metadata.") from None
        if str(metadata.get("sha", "")).lower() != sha:
            raise SourceBundleError("GitHub commit metadata did not match the requested SHA.")

        archive = self._request(
            f"{self.API_BASE}/repos/{self.repository}/tarball/{sha}",
            accept="application/vnd.github+json",
        )
        if len(archive) < 2 or archive[:2] != b"\x1f\x8b":
            raise SourceBundleError("GitHub did not return a valid gzip source archive.")

        digest = hashlib.sha256(archive).hexdigest()
        object_key = f"worker-bundles/{sha}/{digest}.tar.gz"
        self.objects.upload_fileobj(
            io.BytesIO(archive),
            object_key,
            content_type="application/gzip",
        )
        return PublishedBundle(
            repository=self.repository,
            commit_sha=sha,
            object_key=object_key,
            sha256=digest,
            size_bytes=len(archive),
        )
