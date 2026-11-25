# -*- coding: utf-8 -*-
import json

import pytest

from musicmaster.cloud.autodl_pro import AutoDLProClient, AutoDLProError


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def test_requires_token(monkeypatch):
    monkeypatch.delenv("AUTODL_PRO_TOKEN", raising=False)
    with pytest.raises(ValueError, match="AUTODL_PRO_TOKEN"):
        AutoDLProClient()


def test_requires_https():
    with pytest.raises(ValueError, match="HTTPS"):
        AutoDLProClient("secret", base_url="http://api.example.test")


def test_create_instance_uses_configured_4090d_and_auth_header(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.method
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return FakeResponse({"code": "Success", "data": "pro-test123", "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("test-secret", base_url="https://api.example.test", timeout=12)
    instance_id = client.create_instance(image_uuid="image-test", cuda_v_from=124)

    assert instance_id == "pro-test123"
    assert seen["url"] == "https://api.example.test/api/v1/dev/instance/pro/create"
    assert seen["method"] == "POST"
    assert seen["headers"]["Authorization"] == "test-secret"
    assert seen["body"]["gpu_spec_uuid"] == "4090D"
    assert seen["body"]["req_gpu_amount"] == 1
    assert seen["body"]["image_uuid"] == "image-test"
    assert seen["timeout"] == 12


def test_power_on_and_status_use_documented_payloads(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append((request.method, request.full_url, json.loads(request.data.decode("utf-8"))))
        if request.full_url.endswith("/status"):
            return FakeResponse({"code": "Success", "data": "running", "msg": ""})
        return FakeResponse({"code": "Success", "data": None, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    client.power_on("pro-test123", start_command="sleep 1")
    assert client.get_status("pro-test123") == "running"
    assert calls[0][0] == "POST"
    assert calls[0][2] == {
        "instance_uuid": "pro-test123",
        "payload": "gpu",
        "start_command": "sleep 1",
    }
    assert calls[1][0] == "GET"
    assert calls[1][2] == {"instance_uuid": "pro-test123"}


def test_api_error_is_redacted(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({
            "code": "InvalidToken",
            "data": None,
            "msg": "rejected test-secret",
        })

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("test-secret")
    with pytest.raises(AutoDLProError, match="InvalidToken") as exc:
        client.get_status("pro-test123")
    assert "test-secret" not in str(exc.value)


def test_find_instance_scans_every_page_and_returns_matching_instance(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(payload)
        page = payload["page_index"]
        items = ([{"uuid": "pro-other", "status": "running"}]
                 if page == 1 else [{"uuid": "pro-target", "status": "shutdown"}])
        return FakeResponse({"code": "Success", "data": {
            "list": items, "page_index": page, "page_size": 1, "max_page": 2
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    assert client.find_instance("pro-target", page_size=1) == {
        "uuid": "pro-target", "status": "shutdown"
    }
    assert calls == [
        {"page_index": 1, "page_size": 1},
        {"page_index": 2, "page_size": 1},
    ]


def test_find_instance_returns_none_only_after_all_pages(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(payload["page_index"])
        return FakeResponse({"code": "Success", "data": {
            "list": [{"uuid": "pro-other"}], "page_index": payload["page_index"],
            "page_size": 1, "max_page": 3
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    assert client.find_instance("pro-missing", page_size=1) is None
    assert calls == [1, 2, 3]


def test_find_instance_accepts_a_well_formed_empty_instance_list(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"code": "Success", "data": {
            "list": [], "page_index": 1, "page_size": 100, "max_page": 0
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    assert client.find_instance("pro-missing") is None


def test_find_instance_rejects_zero_pages_with_records(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"code": "Success", "data": {
            "list": [{"uuid": "pro-target"}], "max_page": 0
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    with pytest.raises(AutoDLProError, match="zero pages"):
        client.find_instance("pro-target")


def test_find_instance_rejects_incomplete_pagination(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"code": "Success", "data": {"list": []}, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    with pytest.raises(AutoDLProError, match="list/max_page"):
        client.find_instance("pro-target")


def test_find_instances_by_name_scans_all_pages_and_returns_exact_matches(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        calls.append(payload["page_index"])
        page = payload["page_index"]
        items = (
            [{"uuid": "pro-other", "name": "other", "status": "running"}]
            if page == 1 else [
                {"uuid": "pro-match", "name": "XW-worker", "status": "shutdown",
                 "created_at": "2026-11-25T10:00:00+08:00"},
                {"uuid": "pro-near", "name": "XW-worker-extra", "status": "running"},
            ]
        )
        return FakeResponse({"code": "Success", "data": {
            "list": items, "page_index": page, "page_size": 1, "max_page": 2
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    assert client.find_instances_by_name("XW-worker", page_size=1) == [{
        "uuid": "pro-match",
        "name": "XW-worker",
        "status": "shutdown",
        "created_at": "2026-11-25T10:00:00+08:00",
    }]
    assert calls == [1, 2]


def test_find_instances_by_name_returns_all_duplicate_matches(monkeypatch):
    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"code": "Success", "data": {
            "list": [
                {"uuid": "pro-one", "name": "XW-duplicate"},
                {"uuid": "pro-two", "name": "XW-duplicate"},
            ],
            "page_index": payload["page_index"],
            "page_size": 100,
            "max_page": 1,
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    matches = client.find_instances_by_name("XW-duplicate")
    assert [item["uuid"] for item in matches] == ["pro-one", "pro-two"]


def test_find_instances_by_name_rejects_incomplete_or_changed_pagination(monkeypatch):
    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"code": "Success", "data": {
            "list": [],
            "page_index": payload["page_index"] + 1,
            "page_size": 100,
            "max_page": 2,
        }, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    with pytest.raises(AutoDLProError, match="incomplete"):
        client.find_instances_by_name("XW-worker")


def test_rejects_release_with_malformed_id_before_network(monkeypatch):
    called = False

    def fake_urlopen(request, timeout):
        nonlocal called
        called = True
        return FakeResponse({"code": "Success", "data": None, "msg": ""})

    monkeypatch.setattr("musicmaster.cloud.autodl_pro.urlopen", fake_urlopen)
    client = AutoDLProClient("secret")
    with pytest.raises(ValueError):
        client.release_instance("../not-an-instance")
    assert called is False



def test_build_worker_start_command_embeds_bootstrap_helper_without_repo_checkout():
    import base64
    import re
    import zlib
    from pathlib import Path
    from musicmaster.cloud.autodl_pro import build_worker_start_command

    token = "b" * 40
    command = build_worker_start_command("https://api.example.test", token)
    match = re.search(r"payload = '([A-Za-z0-9+/=]+)'", command)
    assert match
    embedded = zlib.decompress(base64.b64decode(match.group(1)))
    expected = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_worker_bundle.py"
    assert embedded == expected.read_bytes()
    assert "MUSICMASTER_BOOTSTRAP_TOKEN=" in command
    assert "MUSICMASTER_WORKER_TOKEN=" in command
    assert token in command
    assert "MUSICMASTER_SKIP_BUNDLE_BOOTSTRAP=1" in command
    assert "\\n" not in command
    assert "set -euo pipefail" in command
    assert "github" not in command.lower()

    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash:
        checked = subprocess.run(
            [bash, "-n"], input=command, text=True, capture_output=True, check=False
        )
        assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize("api_url", [
    "http://api.example.test",
    "https://user:pass@api.example.test",
    "https://api.example.test/path?secret=1",
])
def test_build_worker_start_command_rejects_unsafe_api_url(api_url):
    from musicmaster.cloud.autodl_pro import build_worker_start_command

    with pytest.raises(ValueError, match="HTTPS"):
        build_worker_start_command(api_url, "b" * 40)


def test_build_worker_start_command_rejects_short_bootstrap_token():
    from musicmaster.cloud.autodl_pro import build_worker_start_command

    with pytest.raises(ValueError, match="32"):
        build_worker_start_command("https://api.example.test", "short")
