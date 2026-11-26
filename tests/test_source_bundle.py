# -*- coding: utf-8 -*-
import gzip
import json

import pytest

from musicmaster.cloud.source_bundle import (
    GitHubSourceBundlePublisher,
    SourceBundleError,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.payload)
        result, self.payload = self.payload[:size], self.payload[size:]
        return result


class FakeObjects:
    def __init__(self):
        self.uploaded = None

    def upload_fileobj(self, fileobj, key, *, content_type):
        self.uploaded = (fileobj.read(), key, content_type)


def test_publisher_allows_public_repo_without_token_but_validates_repository(monkeypatch):
    monkeypatch.delenv("MUSICMASTER_GITHUB_READ_TOKEN", raising=False)
    monkeypatch.delenv("MUSICMASTER_GITHUB_REPOSITORY", raising=False)
    publisher = GitHubSourceBundlePublisher(
        objects=FakeObjects(), token="", repository="Trifida/xinsw-music-transcriber"
    )
    assert publisher.token == ""

    with pytest.raises(ValueError, match="owner/repository"):
        GitHubSourceBundlePublisher(
            objects=FakeObjects(), token="", repository="not-a-repo/path/extra"
        )


def test_publish_pins_commit_hashes_archive_and_uploads_immutable_key(monkeypatch):
    commit = "a" * 40
    archive = gzip.compress(b"fake tar archive")
    objects = FakeObjects()
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, dict(request.header_items()), timeout))
        if request.full_url.endswith(f"/commits/{commit}"):
            return FakeResponse(json.dumps({"sha": commit}).encode())
        if request.full_url.endswith(f"/tarball/{commit}"):
            return FakeResponse(archive)
        raise AssertionError(request.full_url)

    monkeypatch.setattr("musicmaster.cloud.source_bundle.urllib.request.urlopen", fake_urlopen)
    publisher = GitHubSourceBundlePublisher(
        objects=objects, token="github-secret", repository="Trifida/xinsw-music-transcriber"
    )
    result = publisher.publish(commit)

    import hashlib
    digest = hashlib.sha256(archive).hexdigest()
    assert result.commit_sha == commit
    assert result.sha256 == digest
    assert result.size_bytes == len(archive)
    assert result.object_key == f"worker-bundles/{commit}/{digest}.tar.gz"
    assert objects.uploaded == (archive, result.object_key, "application/gzip")
    assert len(calls) == 2
    assert all(call[1]["Authorization"] == "Bearer github-secret" for call in calls)


def test_publish_supports_public_github_without_authorization_header(monkeypatch):
    commit = "f" * 40
    archive = gzip.compress(b"public source archive")
    objects = FakeObjects()
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(dict(request.header_items()))
        if request.full_url.endswith(f"/commits/{commit}"):
            return FakeResponse(json.dumps({"sha": commit}).encode())
        if request.full_url.endswith(f"/tarball/{commit}"):
            return FakeResponse(archive)
        raise AssertionError(request.full_url)

    monkeypatch.setattr("musicmaster.cloud.source_bundle.urllib.request.urlopen", fake_urlopen)
    publisher = GitHubSourceBundlePublisher(
        objects=objects, token="", repository="Trifida/xinsw-music-transcriber"
    )
    result = publisher.publish(commit)

    assert result.commit_sha == commit
    assert objects.uploaded[1] == result.object_key
    assert all("Authorization" not in headers for headers in calls)


def test_publish_rejects_short_or_non_hex_commit_sha():
    publisher = GitHubSourceBundlePublisher(
        objects=FakeObjects(), token="secret", repository="owner/repo"
    )
    with pytest.raises(ValueError, match="40-character"):
        publisher.publish("main")


def test_publish_rejects_metadata_sha_mismatch(monkeypatch):
    commit = "b" * 40

    def fake_urlopen(request, timeout):
        return FakeResponse(json.dumps({"sha": "c" * 40}).encode())

    monkeypatch.setattr("musicmaster.cloud.source_bundle.urllib.request.urlopen", fake_urlopen)
    publisher = GitHubSourceBundlePublisher(
        objects=FakeObjects(), token="secret", repository="owner/repo"
    )
    with pytest.raises(SourceBundleError, match="did not match"):
        publisher.publish(commit)


def test_publish_rejects_non_gzip_archive(monkeypatch):
    commit = "d" * 40
    responses = [
        FakeResponse(json.dumps({"sha": commit}).encode()),
        FakeResponse(b"not a gzip archive"),
    ]

    def fake_urlopen(request, timeout):
        return responses.pop(0)

    monkeypatch.setattr("musicmaster.cloud.source_bundle.urllib.request.urlopen", fake_urlopen)
    publisher = GitHubSourceBundlePublisher(
        objects=FakeObjects(), token="secret", repository="owner/repo"
    )
    with pytest.raises(SourceBundleError, match="valid gzip"):
        publisher.publish(commit)


def test_publish_enforces_archive_size_limit(monkeypatch):
    commit = "e" * 40
    responses = [
        FakeResponse(json.dumps({"sha": commit}).encode()),
        FakeResponse(b"\\x1f\\x8b" + b"x" * 200),
    ]

    def fake_urlopen(request, timeout):
        return responses.pop(0)

    monkeypatch.setattr("musicmaster.cloud.source_bundle.urllib.request.urlopen", fake_urlopen)
    publisher = GitHubSourceBundlePublisher(
        objects=FakeObjects(), token="secret", repository="owner/repo", max_bytes=128
    )
    with pytest.raises(SourceBundleError, match="exceeds"):
        publisher.publish(commit)
