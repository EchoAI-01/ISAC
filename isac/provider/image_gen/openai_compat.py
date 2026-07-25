"""OpenAI 兼容图片生成 Provider (J2, SPECIFICATION.md 2.4)。

真实 HTTP 调用实现, 支持任意 OpenAI 兼容 ``/images/generations`` API:
- POST /images/generations, 请求体含 model/prompt/n/size/response_format
- 响应 data[].b64_json 或 data[].url 两种格式都支持
- 生成结果 (b64 解码后 / url 下载后) 写入 ArtifactStore, 返回 ArtifactRef 列表
- 错误分类复用 OpenAICompatProvider 的 _map_http_error / _wrap_network_error

用户配置 api_base + api_key + model 即可接入 DALL-E 3 或任意 OpenAI 兼容
图片生成端点 (阿里通义万相 / 自托管等)。
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Any

from isac.artifacts.models import ArtifactRef
from isac.core.exceptions import LLMError
from isac.provider.base import ImageGenerationProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.artifacts.store import ArtifactStore

logger = get_logger(__name__)

# 图片生成比 chat 慢 (DALL-E 3 通常 10-30 秒), 给足超时
DEFAULT_TIMEOUT = 120.0


class OpenAICompatImageGenProvider(ImageGenerationProvider):
    """OpenAI 兼容图片生成 Provider。

    生成结果写入注入的 ArtifactStore, 不直接返回 bytes 给调用方 (避免二进制
    内容进入历史/日志/记忆)。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        artifact_store: ArtifactStore,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.artifact_store = artifact_store
        self.timeout = timeout
        self.extra = kwargs
        self._client: Any = None  # httpx.AsyncClient 惰性创建

    def _get_client(self) -> Any:
        """惰性创建 httpx.AsyncClient; 已创建则复用 (连接池)。"""
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:  # pragma: no cover
                raise LLMError("httpx 未安装, OpenAICompatImageGenProvider 不可用") from exc
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        *,
        n: int = 1,
        size: str = "1024x1024",
        **kwargs: Any,
    ) -> list[ArtifactRef]:
        """按提示词生成 n 张图, 每张存入 ArtifactStore, 返回 ArtifactRef 列表。

        Args:
            prompt: 图片提示词
            n: 生成图片数 (1-10, OpenAI DALL-E 3 限制)
            size: 图片尺寸 (256x256 / 512x512 / 1024x1024 等, 由 Provider 决定支持)
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "n": n,
            "size": size,
            # 优先 b64_json, 避免二次 HTTP 下载; 若 Provider 不支持会返回 url
            "response_format": "b64_json",
        }
        payload.update(kwargs)
        client = self._get_client()
        try:
            response = await client.post("/images/generations", json=payload)
        except TimeoutError as exc:
            raise LLMError(f"图片生成请求超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMError(
                f"图片生成响应 JSON 解析失败: {exc}",
                retriable=False,
                context={"body": response.text[:500]},
            ) from exc
        return await self._store_images(data, prompt)

    async def _store_images(self, data: dict[str, Any], prompt: str) -> list[ArtifactRef]:
        """把响应 data[].b64_json 或 data[].url 图片写入 ArtifactStore, 返回引用列表。"""
        items = data.get("data") or []
        if not items:
            raise LLMError(
                "图片生成响应无 data 字段或为空",
                retriable=False,
                context={"body": json.dumps(data)[:500]},
            )
        refs: list[ArtifactRef] = []
        for item in items:
            img_bytes: bytes | None = None
            mime = "image/png"  # DALL-E 默认 png; 部分兼容端点可能返回其他格式
            if item.get("b64_json"):
                try:
                    img_bytes = base64.b64decode(item["b64_json"])
                except (ValueError, TypeError) as exc:
                    logger.warning("b64_json 解码失败, 跳过该图", error=str(exc))
                    continue
            elif item.get("url"):
                img_bytes = await self._download_url(str(item["url"]))
            else:
                continue
            if not img_bytes:
                continue
            ref = await self.artifact_store.put(
                img_bytes,
                kind="image",
                mime_type=mime,
                metadata={
                    "prompt": prompt,
                    "model": self.model,
                    "provider": "openai_compat",
                },
            )
            refs.append(ref)
        if not refs:
            raise LLMError(
                "图片生成响应中无可用 b64_json 或 url (全部解析失败)",
                retriable=False,
            )
        return refs

    async def _download_url(self, url: str) -> bytes:
        """下载远程图片为 bytes (用于 url 响应格式)。"""
        client = self._get_client()
        try:
            response = await client.get(url)
        except TimeoutError as exc:
            raise LLMError(f"图片下载超时: {exc}", retriable=True) from exc
        except Exception as exc:
            raise OpenAICompatProvider._wrap_network_error(exc) from exc
        if response.status_code >= 400:
            raise OpenAICompatProvider._map_http_error(
                response.status_code, response.content
            )
        return response.content

    def get_model_name(self) -> str:
        return self.model

    async def aclose(self) -> None:
        """关闭 httpx.AsyncClient, 释放连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
