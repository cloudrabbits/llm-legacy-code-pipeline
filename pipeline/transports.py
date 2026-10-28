"""传输层：只负责「把 RequestSpec 发出去，把原始 dict 拿回来」。

不含任何后端语义；超时/HTTP 状态在此统一翻译成本项目异常，
让 `backend.py` 与编排器只面对 PipelineError 家族。
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass
from typing import Any, Callable

from .errors import BackendError, BackendTimeoutError
from .profiles.base import RequestSpec

__all__ = ["TransportResponse", "Transport", "HttpJsonTransport", "StubTransport", "get_transport"]


@dataclass
class TransportResponse:
    raw: dict[str, Any]
    latency_ms: int


class Transport(abc.ABC):
    """传输抽象。"""

    @abc.abstractmethod
    def send(self, spec: RequestSpec) -> TransportResponse: ...


class HttpJsonTransport(Transport):
    """POST JSON，收 JSON。DeepSeek 与 Ollama 共用同一实现。"""

    def __init__(self, *, connect_timeout: float = 10.0, write_timeout: float = 60.0, client: Any = None) -> None:
        self.connect_timeout = connect_timeout
        self.write_timeout = write_timeout
        self._client = client

    def send(self, spec: RequestSpec) -> TransportResponse:
        import httpx  # 延迟导入：纯离线场景（stub transport）不需要装

        timeout = httpx.Timeout(
            connect=self.connect_timeout,
            read=spec.timeout_sec,
            write=self.write_timeout,
            pool=self.connect_timeout,
        )
        started = time.monotonic()
        try:
            poster = self._client.post if self._client is not None else httpx.post
            resp = poster(spec.url, headers=spec.headers, json=spec.payload, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(f"请求超时（{spec.timeout_sec}s）: {exc}", timeout_sec=spec.timeout_sec) from exc
        except httpx.HTTPError as exc:
            raise BackendError(f"网络错误: {exc}", retryable=True) from exc
        latency_ms = int((time.monotonic() - started) * 1000)

        if resp.status_code >= 400:
            # 4xx 中仅 408/429 值得重试；5xx 一律可重试
            retryable = resp.status_code >= 500 or resp.status_code in (408, 429)
            raise BackendError(
                f"HTTP {resp.status_code}: {resp.text[:400]}",
                status_code=resp.status_code,
                retryable=retryable,
                raw=resp.text[:2000],
            )
        try:
            raw = resp.json()
        except ValueError as exc:
            raise BackendError("响应不是合法 JSON", retryable=True) from exc
        if not isinstance(raw, dict):
            raise BackendError("响应顶层不是对象", retryable=True, raw=raw)
        return TransportResponse(raw=raw, latency_ms=latency_ms)


class StubTransport(Transport):
    """确定性桩传输，供契约测试使用：不发网络请求，只记录与回放。

    Args:
        responder: `(spec) -> dict` 返回原始响应；也可直接 raise PipelineError 家族异常。
    """

    def __init__(self, responder: Callable[[RequestSpec], dict[str, Any]]) -> None:
        self.responder = responder
        #: 按调用顺序记录所有请求，用于断言「超限任务根本没有发出」
        self.calls: list[RequestSpec] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def send(self, spec: RequestSpec) -> TransportResponse:
        self.calls.append(spec)
        raw = self.responder(spec)
        return TransportResponse(raw=raw, latency_ms=0)


#: transport 名 -> 连接超时预设。
#: 报文本身完全同构（POST JSON 收 JSON），差异只在超时尺度：
#: `ollama_native` 对应本地模型首次加载（规格书建议 OLLAMA_LOAD_TIMEOUT=900）。
_TRANSPORT_PRESETS: dict[str, dict[str, float]] = {
    "http_json": {"connect_timeout": 10.0},
    "ollama_native": {"connect_timeout": 900.0},
}


def get_transport(name: str, **kwargs: Any) -> Transport:
    """按 transport 名取传输实现；`stub` 需自带 responder。"""
    if name == "stub":
        return StubTransport(kwargs["responder"])
    preset = _TRANSPORT_PRESETS.get(name)
    if preset is None:
        raise BackendError(f"未注册的 transport: {name}；可用: {sorted(_TRANSPORT_PRESETS)}")
    return HttpJsonTransport(**{**preset, **kwargs})
