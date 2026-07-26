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

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.core.exceptions import LLMError, RateLimitError
from isac.core.types import LLMChunk, LLMResponse, TokenUsage, ToolCall
from isac.provider.base import LLMProvider, ModelCapabilities
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.artifacts.models import MediaInput

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

    async def vision_chat(
        self,
        media: MediaInput,
        prompt: str,
        *,
        system: str = "",
        **kwargs: Any,
    ) -> LLMResponse:
        """视觉理解: 把 image 作为 image_url content 与 prompt 一起发给多模态 LLM。

        要求模型支持视觉输入 (gpt-4o / gpt-4-vision 等)。media.kind 必须是 "image",
        media.uri 必须是本地绝对路径 (MediaNormalizer 已校验), 这里读文件转 base64
        data URL 内联到请求体 (避免 LLM 端二次 HTTP 下载; 适合 < 5MB 的图)。

        Args:
            media: 输入图片 (kind="image", uri 为本地绝对路径)
            prompt: 关于图片的自然语言提问
            system: 可选 system prompt (默认空, 调用方可设行为约束)
        """
        if media.kind != "image":
            raise LLMError(
                f"vision_chat 只支持 kind=image, 收到 kind={media.kind}",
                retriable=False,
            )
        img_path = Path(media.uri)
        try:
            img_bytes = await asyncio.to_thread(img_path.read_bytes)
        except FileNotFoundError as exc:
            raise LLMError(
                f"vision_chat 输入图片不存在: {media.uri}",
                retriable=False,
            ) from exc
        except OSError as exc:
            raise LLMError(
                f"vision_chat 输入图片读取失败: {exc}",
                retriable=False,
            ) from exc
        mime = media.mime_type or "image/png"
        b64 = base64.b64encode(img_bytes).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]
        return await self.chat(system=system, messages=messages, **kwargs)

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
        if stream:
            # CR3-H4: 要求最终 chunk 携带 usage (OpenAI 语义), 否则流式回合的
            # token 预算永远记 0、Budget 门控对流式失效。调用方可用
            # kwargs stream_options=None 显式关闭 (个别兼容端点不认该字段)。
            payload.setdefault("stream_options", {"include_usage": True})
        # kwargs 覆盖默认参数 (temperature/top_p/max_tokens 等)
        payload.update(kwargs)
        if payload.get("stream_options") is None:
            payload.pop("stream_options", None)
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
            usage = self._parse_usage(data.get("usage", {}) or {})
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
    def _parse_usage(usage_data: dict[str, Any]) -> TokenUsage:
        """解析 usage 及其 J1 明细子字段 (prompt/completion_tokens_details)。

        cached_tokens/reasoning_tokens/audio_tokens 是 prompt_tokens/completion_tokens
        的子集 (OpenAI 语义), 字段不存在时保持 0, 不猜测。
        """
        prompt_details = usage_data.get("prompt_tokens_details") or {}
        completion_details = usage_data.get("completion_tokens_details") or {}
        return TokenUsage(
            prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
            total_tokens=int(usage_data.get("total_tokens", 0) or 0),
            cache_read_tokens=int(prompt_details.get("cached_tokens", 0) or 0),
            reasoning_tokens=int(completion_details.get("reasoning_tokens", 0) or 0),
            audio_input_tokens=int(prompt_details.get("audio_tokens", 0) or 0),
            audio_output_tokens=int(completion_details.get("audio_tokens", 0) or 0),
        )

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
        """解析 SSE 流: data: <json>\\n\\n; 末尾 data: [DONE] 结束。

        CR3-H4: 真实 OpenAI 流式把一个工具调用拆到 N 个 delta (首块带 id+name,
        后续只带 arguments 片段, 并行调用按 index 区分)。此前把每个 delta 当完整
        调用、对片段单独 json.loads —— 合并结果是参数为空的调用 + 一串 id/name
        为空的幽灵调用。现在按 index 累积分片, 流结束后装配为完整 ToolCall 逐个
        yield (与 LLMChunk 契约一致: tool_call 只在完整时出现)。
        """
        pending_tool_calls: dict[int, dict[str, str]] = {}
        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk_json = json.loads(data_str)
            except json.JSONDecodeError as exc:
                logger.warning("SSE chunk JSON 解析失败, 跳过", error=str(exc), line=line)
                continue
            yield self._parse_chunk(chunk_json, pending_tool_calls)
        for tool_call in self._assemble_tool_calls(pending_tool_calls):
            yield LLMChunk(tool_call=tool_call, finish_reason="tool_calls")

    @staticmethod
    def _parse_chunk(chunk_json: dict[str, Any], pending_tool_calls: dict[int, dict[str, str]]) -> LLMChunk:
        """从单个 SSE chunk JSON 提取 delta/usage, 并把工具调用分片累积进 pending。

        分片累积 (CR3-H4): delta.tool_calls 的每个条目按 index 归并 —— id/name
        只在首个分片出现 (非空才覆盖), arguments 是字符串片段做拼接; 完整装配
        推迟到流结束 (_assemble_tool_calls), 本方法产出的 chunk 不携带 tool_call。
        """
        delta_content = ""
        delta_reasoning = ""
        finish_reason: str | None = None
        usage = TokenUsage()

        choices = chunk_json.get("choices") or []
        if choices:
            choice = choices[0]
            delta = choice.get("delta", {}) or {}
            delta_content = str(delta.get("content", "") or "")
            delta_reasoning = str(delta.get("reasoning_content", "") or "")
            for tc in delta.get("tool_calls", []) or []:
                try:
                    index = int(tc.get("index", 0) or 0)
                except (TypeError, ValueError):
                    index = 0
                entry = pending_tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    entry["id"] = str(tc["id"])
                function = tc.get("function", {}) or {}
                if function.get("name"):
                    entry["name"] = str(function["name"])
                fragment = function.get("arguments", "")
                if fragment:
                    entry["arguments"] += str(fragment)
            finish_reason = choice.get("finish_reason")
        usage_data = chunk_json.get("usage")
        if usage_data:
            usage = OpenAICompatProvider._parse_usage(usage_data)
        return LLMChunk(
            delta_content=delta_content,
            delta_reasoning=delta_reasoning,
            tool_call=None,
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _assemble_tool_calls(pending_tool_calls: dict[int, dict[str, str]]) -> list[ToolCall]:
        """把累积的工具调用分片装配为完整 ToolCall 列表 (按 index 升序)。

        参数片段拼接后整体 json.loads; 解析失败或 id/name 均为空的残片跳过
        (与非流式 _parse_tool_calls 的"单个失败不阻塞整体"策略一致)。
        """
        tool_calls: list[ToolCall] = []
        for index in sorted(pending_tool_calls):
            entry = pending_tool_calls[index]
            if not entry["id"] and not entry["name"]:
                logger.warning("流式工具调用分片缺 id/name, 跳过", index=index)
                continue
            try:
                arguments = json.loads(entry["arguments"] or "{}")
            except json.JSONDecodeError as exc:
                logger.warning(
                    "流式工具调用参数拼接后 JSON 解析失败, 参数置空",
                    index=index, name=entry["name"], error=str(exc),
                )
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(ToolCall(id=entry["id"], name=entry["name"], arguments=arguments))
        return tool_calls

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
