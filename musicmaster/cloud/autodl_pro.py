# -*- coding: utf-8 -*-
"""AutoDL 容器实例 Pro 的最小生命周期 API 客户端。

只负责创建/查询/启停/释放实例；不在这里传输用户音频、不保存密钥、不启动付费实例。
真实任务调度和对象存储由上层 job dispatcher 负责。
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AutoDLProError(RuntimeError):
    """AutoDL Pro API 返回错误或请求失败。"""


class AutoDLProClient:
    API_BASE = "https://api.autodl.com"

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._token = (token or os.environ.get("AUTODL_PRO_TOKEN", "")).strip()
        if not self._token:
            raise ValueError("缺少 AutoDL Pro Token；请在服务端设置 AUTODL_PRO_TOKEN。")
        self._base_url = (base_url or self.API_BASE).rstrip("/")
        self._timeout = float(timeout)
        if self._timeout <= 0:
            raise ValueError("timeout 必须大于 0。")

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = Request(
            self._base_url + path,
            data=body,
            headers={
                "Authorization": self._token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise AutoDLProError(f"AutoDL Pro HTTP {exc.code}: {detail}") from None
        except URLError as exc:
            raise AutoDLProError(f"AutoDL Pro 网络请求失败：{exc.reason}") from None
        except TimeoutError:
            raise AutoDLProError("AutoDL Pro 请求超时。") from None

        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AutoDLProError("AutoDL Pro 返回了无法解析的响应。") from None
        if not isinstance(result, dict):
            raise AutoDLProError("AutoDL Pro 返回格式异常：响应不是对象。")
        if result.get("code") != "Success":
            code = result.get("code", "Unknown")
            message = str(result.get("msg") or "未提供错误说明")[:500]
            raise AutoDLProError(f"AutoDL Pro API 错误({code})：{message}")
        return result.get("data")

    def create_instance(
        self,
        *,
        image_uuid: str,
        cuda_v_from: int,
        gpu_spec_uuid: str = "4090D",
        req_gpu_amount: int = 1,
        expand_system_disk_by_gb: int = 0,
        instance_name: str = "XinsW Music Transcriber",
        start_command: str | None = None,
        data_center_list: list[str] | None = None,
    ) -> str:
        """按量创建 Pro 实例；4090D 为当前默认规格，镜像必须由部署配置提供。"""
        if not image_uuid.strip():
            raise ValueError("必须提供 AutoDL 镜像 UUID。")
        if not 1 <= int(req_gpu_amount) <= 4:
            raise ValueError("req_gpu_amount 必须在 1–4 之间。")
        if not 0 <= int(expand_system_disk_by_gb) <= 500:
            raise ValueError("expand_system_disk_by_gb 必须在 0–500 之间。")
        if int(cuda_v_from) < 0:
            raise ValueError("cuda_v_from 不能为负数。")

        payload: dict[str, Any] = {
            "req_gpu_amount": int(req_gpu_amount),
            "expand_system_disk_by_gb": int(expand_system_disk_by_gb),
            "gpu_spec_uuid": gpu_spec_uuid,
            "image_uuid": image_uuid.strip(),
            "cuda_v_from": int(cuda_v_from),
            "instance_name": instance_name,
        }
        if start_command:
            payload["start_command"] = start_command
        if data_center_list:
            payload["data_center_list"] = list(data_center_list)

        instance_uuid = self._request("POST", "/api/v1/dev/instance/pro/create", payload)
        if not isinstance(instance_uuid, str) or not instance_uuid.startswith("pro-"):
            raise AutoDLProError("AutoDL Pro 创建实例未返回有效实例 ID。")
        return instance_uuid

    def get_status(self, instance_uuid: str) -> str:
        data = self._request(
            "GET", "/api/v1/dev/instance/pro/status",
            {"instance_uuid": self._validate_instance_id(instance_uuid)},
        )
        if not isinstance(data, str):
            raise AutoDLProError("AutoDL Pro 状态响应格式异常。")
        return data

    def get_snapshot(self, instance_uuid: str) -> dict:
        data = self._request(
            "GET", "/api/v1/dev/instance/pro/snapshot",
            {"instance_uuid": self._validate_instance_id(instance_uuid)},
        )
        if not isinstance(data, dict):
            raise AutoDLProError("AutoDL Pro 实例详情响应格式异常。")
        # 快照可能含 SSH 密码/Jupyter Token；调用方不得将完整结果写入普通日志。
        return data

    def list_instances(self, *, page_index: int = 1, page_size: int = 20) -> dict:
        if page_index < 1 or not 1 <= page_size <= 100:
            raise ValueError("page_index 必须 >=1，page_size 必须在 1–100 之间。")
        data = self._request(
            "POST", "/api/v1/dev/instance/pro/list",
            {"page_index": page_index, "page_size": page_size},
        )
        if not isinstance(data, dict):
            raise AutoDLProError("AutoDL Pro 实例列表响应格式异常。")
        return data

    def power_on(self, instance_uuid: str, *, start_command: str | None = None) -> None:
        payload: dict[str, Any] = {
            "instance_uuid": self._validate_instance_id(instance_uuid),
            "payload": "gpu",
        }
        if start_command:
            payload["start_command"] = start_command
        self._request("POST", "/api/v1/dev/instance/pro/power_on", payload)

    def power_off(self, instance_uuid: str) -> None:
        self._request(
            "POST", "/api/v1/dev/instance/pro/power_off",
            {"instance_uuid": self._validate_instance_id(instance_uuid)},
        )

    def release_instance(self, instance_uuid: str) -> None:
        """释放前调用方必须先关机并确认关机完成。"""
        self._request(
            "POST", "/api/v1/dev/instance/pro/release",
            {"instance_uuid": self._validate_instance_id(instance_uuid)},
        )

    @staticmethod
    def _validate_instance_id(instance_uuid: str) -> str:
        value = str(instance_uuid).strip()
        if not value.startswith("pro-") or len(value) > 80:
            raise ValueError("无效的 AutoDL Pro 实例 ID。")
        return value
