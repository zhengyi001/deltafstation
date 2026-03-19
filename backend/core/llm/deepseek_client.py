"""
DeepSeek LLM Client（OpenAI-compatible SDK 封装）

面向本项目的最小约定：
- 通过 `openai` Python SDK 调用 DeepSeek OpenAI-compatible API（base_url 通常为 `https://api.deepseek.com/v1`）。
- 提供两种调用方式：
  - chat: 非流式，返回完整 reply + usage
  - stream: 流式，逐段 yield 文本 delta（由上层负责拼接）
- 内置轻量重试：仅对 429 / 5xx 做指数退避（次数可配），避免临时抖动导致失败。

注意：
- 本模块只负责“调用模型”，不负责 prompt 组装、工具调用循环、RAG 等编排逻辑。
"""

import os
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar

from openai import OpenAI

T = TypeVar("T")


class DeepSeekClient:
    """DeepSeek API 客户端（OpenAI-compatible）。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        """
        Args:
            api_key: DeepSeek API key（优先使用该值；若为空则回退到环境变量 DEEPSEEK_API_KEY）
            base_url: OpenAI-compatible API 根地址（例如 https://api.deepseek.com/v1）
            model: 模型名（deepseek-chat / deepseek-reasoner）
            timeout: 单次请求超时（秒）
            max_retries: 重试次数（仅对 429/5xx 生效）
        """
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))

        resolved_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        self._client: Optional[OpenAI] = OpenAI(api_key=resolved_key, base_url=self.base_url) if resolved_key else None

    def _get_client(self) -> OpenAI:
        """获取（或延迟创建）OpenAI SDK client。"""
        if self._client is not None:
            return self._client
        api_key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY env var")
        self._client = OpenAI(api_key=api_key, base_url=self.base_url)
        return self._client

    def _status_code(self, err: Exception) -> Optional[int]:
        """从 OpenAI SDK 异常中提取 HTTP 状态码（若存在）。"""
        return getattr(err, "status_code", None)

    def _with_retry(self, fn: Callable[[], T]) -> T:
        """对可重试错误执行指数退避重试。"""
        attempt = 0
        while True:
            try:
                return fn()
            except Exception as e:
                attempt += 1
                code = self._status_code(e)
                retryable = code in (429, 500, 502, 503, 504)
                if (not retryable) or (attempt > self.max_retries):
                    raise
                # simple backoff: 0.5s, 1s, 2s...
                time.sleep(0.5 * (2 ** (attempt - 1)))

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """非流式对话，返回 reply/model/usage。"""
        client = self._get_client()
        resp = self._with_retry(
            lambda: client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                timeout=float(timeout if timeout is not None else self.timeout),
            )
        )
        msg = resp.choices[0].message
        return {
            "reply": msg.content or "",
            "model": self.model,
            "usage": (resp.usage.model_dump() if resp.usage else {}),
        }

    def stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        timeout: Optional[float] = None,
    ):
        """流式对话，逐段 yield 文本 delta（上层拼接成完整回复）。"""
        client = self._get_client()
        stream = self._with_retry(
            lambda: client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                timeout=float(timeout if timeout is not None else self.timeout),
                stream=True,
            )
        )
        for event in stream:
            delta = event.choices[0].delta
            text = getattr(delta, "content", None)
            if text:
                yield text


deepseek_client = DeepSeekClient()

