"""开放弹幕网络 API 客户端：签名、限速、配额与本地缓存。

签名算法（与官方文档一致）：
    signature = base64( sha256( appId + timestamp + path + appSecret ) )
请求头：X-AppId / X-Timestamp / X-Signature
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


API_BASE = "https://api.dandanplay.net"


class BudgetExceeded(RuntimeError):
    """单次运行内的请求数超过自设上限（防止误触发大规模抓取）。"""


class ApiError(RuntimeError):
    pass


def sign(app_id: str, app_secret: str, timestamp: int, path: str) -> str:
    """按官方规则生成签名。path 为不含域名与查询参数的接口路径。"""
    raw = f"{app_id}{timestamp}{path}{app_secret}".encode("utf-8")
    return base64.b64encode(hashlib.sha256(raw).digest()).decode("ascii")


@dataclass
class RequestPolicy:
    """把「按需调用」写成代码，而不是写在文档里。"""

    min_interval: float = 1.0    # 两次请求之间的最小间隔（秒）
    max_requests: int = 30       # 单次运行最多请求数
    timeout: int = 15


class ApiClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        policy: Optional[RequestPolicy] = None,
        base_url: str = API_BASE,
    ) -> None:
        if not app_id or not app_secret:
            raise ApiError("缺少 AppId / AppSecret，请通过环境变量或配置文件提供")
        self.app_id = app_id
        self.app_secret = app_secret
        self.policy = policy or RequestPolicy()
        self.base_url = base_url.rstrip("/")
        self.calls = 0
        self._last_call = 0.0

    # ---- 内部工具 ----
    def _throttle(self) -> None:
        wait = self.policy.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _budget(self) -> None:
        if self.calls >= self.policy.max_requests:
            raise BudgetExceeded(
                f"本次运行已达到请求上限 {self.policy.max_requests} 次。"
                "如需继续，请分批运行，不要调高上限做批量抓取。"
            )
        self.calls += 1

    def _headers(self, path: str) -> Dict[str, str]:
        ts = int(time.time())
        return {
            "X-AppId": self.app_id,
            "X-Timestamp": str(ts),
            "X-Signature": sign(self.app_id, self.app_secret, ts, path),
            "Accept": "application/json",
            "User-Agent": "DanmakuBridge/0.3 (+https://github.com/)",
        }

    def _open(self, req: urllib.request.Request) -> Any:
        with urllib.request.urlopen(req, timeout=self.policy.timeout) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)

    # ---- 公开方法 ----
    def match(self, file_name: str, file_size: int, file_hash: Optional[str]) -> Dict[str, Any]:
        """POST /api/v2/match —— 用文件名 + 大小 + 哈希识别剧集。"""
        path = "/api/v2/match"
        body: Dict[str, Any] = {
            "fileName": file_name,
            "fileSize": file_size,
            "matchMode": "hashAndFileName" if file_hash else "fileNameOnly",
        }
        if file_hash:
            body["fileHash"] = file_hash

        self._budget()
        self._throttle()
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = dict(self._headers(path))
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method="POST")
        return self._open(req)

    def comments(self, episode_id: int, with_related: bool = True, ch_convert: int = 0) -> Dict[str, Any]:
        """GET /api/v2/comment/{episodeId} —— 拉取该集弹幕。"""
        path = f"/api/v2/comment/{int(episode_id)}"
        params = {
            "withRelated": "true" if with_related else "false",
            "chConvert": str(ch_convert),
        }
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"

        self._budget()
        self._throttle()
        req = urllib.request.Request(url, headers=self._headers(path), method="GET")
        return self._open(req)


class MockClient:
    """离线客户端：读取 fixtures 目录下的固定响应，用于测试与演示。

    仅用于本地验证流程，不会向服务器发出任何请求。
    """

    def __init__(self, fixture_dir: str) -> None:
        self.dir = fixture_dir
        self.calls = 0

    def _load(self, name: str) -> Dict[str, Any]:
        with open(os.path.join(self.dir, name), "r", encoding="utf-8") as fh:
            return json.load(fh)

    def match(self, file_name: str, file_size: int, file_hash: Optional[str]) -> Dict[str, Any]:
        self.calls += 1
        return self._load("match.json")

    def comments(self, episode_id: int, with_related: bool = True, ch_convert: int = 0) -> Dict[str, Any]:
        self.calls += 1
        return self._load("comment.json")


class MatchCache:
    """识别结果缓存。官方文档建议缓存 2–6 小时，这里默认 6 小时。"""

    def __init__(self, path: str, ttl: int = 6 * 3600) -> None:
        self.path = path
        self.ttl = ttl
        self._data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self._data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    @staticmethod
    def key(file_name: str, file_size: int) -> str:
        return f"{file_name}|{file_size}"

    def get(self, file_name: str, file_size: int) -> Optional[Dict[str, Any]]:
        item = self._data.get(self.key(file_name, file_size))
        if not item:
            return None
        if time.time() - item.get("fetched_at", 0) > self.ttl:
            return None
        return item.get("payload")

    def put(self, file_name: str, file_size: int, payload: Dict[str, Any]) -> None:
        self._data[self.key(file_name, file_size)] = {
            "fetched_at": time.time(),
            "payload": payload,
        }
        self.flush()

    def flush(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
