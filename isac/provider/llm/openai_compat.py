"""OpenAI 兼容 Provider (K2, DEVELOPMENT_PLAN.md)。

真实 HTTP 调用实现, 支持 OpenAI / DeepSeek / Moonshot / 任意 OpenAI 兼容 API:
- chat(): 非流式 POST /chat/completions, 解析 choices[0].message + tool_calls + usage
- chat_stream(): SSE 流式解析 (data: <json>\\n\\n), 逐 chunk yield LLMChunk
- 错误分类: 429 → RateLimitError; 5xx → LLMError(retriable=True); 4xx (非 429) →
  LLMError(retriable=False); 超时 → LLMError(retriable=True); JSON 解析失败 →
  LLMError(retriable=False)
- 连接池: httpx.AsyncClient 持有, aclose() 释放 (ApplicationRuntime 关闭时调用)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from isac.core.exceptions import LLMError, RateLimitError
from isac.core.types import LLMChunk, LLMResponse, TokenUsage, ToolCall
from isac.provider.base import LLMProvider, ModelCapabilities
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# OpenAI 兼容 API 的默认超时与重试 (秒) — HTTP 层, 与 ProviderManager.chat_with_retry
# 的应用层重试 (3 次指数退避) 互补。
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 0  # 应用层 chat_with_retry 已重试, HTTP 层不重复重试


class OpenAICompatProvider(LLMProvider):
    """OpenAI 兼容 API Provider。

    真实实现: httpx.AsyncClient 调用 {base_url}/chat/completions。
    错误映射按状态码分类, 不再抛 NotImplementedError。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        **kwargs: Any,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.extra = kwargs
        self._client: Any = None  # httpx.AsyncClient 惰性创建

    def _get_client(self) -> Any:
        """惰性创建 httpx.AsyncClient; 已创建则复用 (连接池)。"""
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover - 测试环境都装了 httpx
                raise LLMError("httpx 未安装, OpenAICompatProvider 不可用") from exc
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """非流式 chat 请求, 返回完整 LLMResponse (含 content/tool_calls/usage)。"""
        payload = self._build_payload(system, messages, tools, kwargs, stream=False)
        data = await self._post_and_parse(payload)
        return self._parse_response(data)

    async def chat_stream(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMChunk]:
        """流式 chat 请求, SSE 解析为 LLMChunk 迭代器。"""
        payload = self._build_payload(system, messages, tools, kwargs, stream=True)
        client = self._get_client()
        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    raise self._map_http_error(response.status_code, body)
                async for chunk in self._parse_sse_stream(response):
                    yield chunk
        except (LLMError, RateLimitError):
            raise
        except TimeoutError as exc:
            raise LLMError(f"OpenAI 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise self._wrap_network_error(exc) from exc

    def get_model_name(self) -> str:
        return self.model

    def get_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(supports_tools=True, supports_streaming=True)

    async def aclose(self) -> None:
        """关闭 httpx.AsyncClient, 释放连接池 (ApplicationRuntime 关闭时调用)。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── 内部: 请求构造 / 响应解析 / 错误映射 ──────────────────

    def _build_payload(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None,
        kwargs: dict,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """构造 OpenAI chat/completions 请求体。"""
        full_messages: list[dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
        # kwargs 覆盖默认参数 (temperature/top_p/max_tokens 等)
        payload.update(kwargs)
        return payload

    async def _post_and_parse(self, payload: dict[str, Any]) -> dict[str, Any]:
        """非流式 POST + 解析 JSON; 按 HTTP 状态码分类错误。"""
        client = self._get_client()
        try:
            response = await client.post("/chat/completions", json=payload)
        except TimeoutError as exc:
            raise LLMError(f"OpenAI 请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise self._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise self._map_http_error(response.status_code, response.content)
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                f"OpenAI 响应 JSON 解析失败: {exc}",
                retriable=False,
                context={"body": response.text[:500]},
            ) from exc

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        """从 OpenAI 响应 JSON 提取 content/tool_calls/usage。"""
        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = str(message.get("content", "") or "")
            reasoning = str(message.get("reasoning_content", "") or "")
            tool_calls = self._parse_tool_calls(message.get("tool_calls", []))
            usage_data = data.get("usage", {}) or {}
            usage = TokenUsage(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_data.get("total_tokens", 0) or 0),
            )
            return LLMResponse(
                content=content,
                reasoning=reasoning,
                tool_calls=tool_calls,
                usage=usage,
                model=str(data.get("model", self.model) or self.model),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(
                f"OpenAI 响应结构不符合预期: {exc}",
                retriable=False,
                context={"body": json.dumps(data)[:500]},
            ) from exc

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
        """解析 message.tool_calls 为 ToolCall 列表。"""
        tool_calls: list[ToolCall] = []
        for raw in raw_tool_calls or []:
            try:
                function = raw.get("function", {})
                arguments = json.loads(function.get("arguments", "{}") or "{}")
                tool_calls.append(
                    ToolCall(
                        id=str(raw.get("id", "")),
                        name=str(function.get("name", "")),
                        arguments=arguments,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                # 单个 tool_call 解析失败不阻塞整个响应; 跳过该调用
                logger.warning("tool_call 解析失败, 跳过", raw=raw)
                continue
        return tool_calls

    async def _parse_sse_stream(self, response: Any) -> AsyncIterator[LLMChunk]:
        """解析 SSE 流: data: <json>\\n\\n; 末尾 data: [DONE] 结束。"""
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                return
            try:
                chunk_json = json.loads(data_str)
            except json.JSONDecodeError as exc:
                logger.warning("SSE chunk JSON 解析失败, 跳过", error=str(exc), line=line)
                continue
            yield self._parse_chunk(chunk_json)

    @staticmethod
    def _parse_chunk(chunk_json: dict[str, Any]) -> LLMChunk:
        """从单个 SSE chunk JSON 提取 delta + tool_call + usage。"""
        delta_content = ""
        delta_reasoning = ""
        tool_call: ToolCall | None = None
        finish_reason: str | None = None
        usage = TokenUsage()

        choices = chunk_json.get("choices") or []
        if choices:
            choice = choices[0]
            delta = choice.get("delta", {}) or {}
            delta_content = str(delta.get("content", "") or "")
            delta_reasoning = str(delta.get("reasoning_content", "") or "")
            tc_list = delta.get("tool_calls", [])
            if tc_list:
                tc = tc_list[0]
                function = tc.get("function", {}) or {}
                try:
                    arguments = json.loads(function.get("arguments", "{}") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                tool_call = ToolCall(
                    id=str(tc.get("id", "")),
                    name=str(function.get("name", "")),
                    arguments=arguments,
                )
            finish_reason = choice.get("finish_reason")
        usage_data = chunk_json.get("usage")
        if usage_data:
            usage = TokenUsage(
                prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
                completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                total_tokens=int(usage_data.get("total_tokens", 0) or 0),
            )
        return LLMChunk(
            delta_content=delta_content,
            delta_reasoning=delta_reasoning,
            tool_call=tool_call,
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _map_http_error(status_code: int, body: bytes) -> LLMError | RateLimitError:
        """按 HTTP 状态码分类: 429 限流, 5xx 服务端错误 (可重试), 4xx 客户端错误。"""
        try:
            text = body.decode("utf-8", errors="replace")[:500]
        except Exception:  # pragma: no cover - bytes 总能 decode
            text = ""
        message = f"OpenAI API {status_code}: {text}"
        if status_code == 429:
            return RateLimitError(message)
        if status_code >= 500:
            return LLMError(message, retriable=True)
        # 4xx (非 429): 不可重试, 如 401 鉴权失败 / 400 参数错误
        return LLMError(message, retriable=False)

    @staticmethod
    def _wrap_network_error(exc: Exception) -> LLMError:
        """把 httpx 的网络异常 (ConnectError/ReadError/RemoteProtocolError) 包装为 LLMError。"""
        exc_name = type(exc).__name__
        return LLMError(
            f"OpenAI 网络错误 ({exc_name}): {exc}",
            retriable=True,
        )
