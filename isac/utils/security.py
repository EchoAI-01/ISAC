"""API Key 加密存储 (K7, DEVELOPMENT_PLAN.md)。

- 算法: AES-256-GCM (cryptography 库)
- 密钥来源: 环境变量 ISAC_SECRET_KEY (32 字节, base64 编码)
- 存储位置: data/.secrets.enc (JSON dict: key -> {nonce, ciphertext, tag})

K7 验收: 不再是 NotImplementedError 桩, 真实可加解密; 未配置 ISAC_SECRET_KEY
时抛 RuntimeError 提示运维补环境, 不静默降级到明文。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any


class SecretStore:
    """敏感信息加密存储 (AES-256-GCM)。

    用法:
        store = SecretStore("data/.secrets.enc")
        await store.set("openai_api_key", "sk-xxx")
        value = await store.get("openai_api_key")  # "sk-xxx" 或 None
    """

    def __init__(self, path: str, secret_key_env: str = "ISAC_SECRET_KEY"):
        self.path = Path(path)
        self.secret_key_env = secret_key_env
        self._key: bytes | None = None
        self._cache: dict[str, dict[str, str]] | None = None

    def _load_key(self) -> bytes:
        """从环境变量加载 32 字节 base64 编码的 AES 密钥。"""
        if self._key is not None:
            return self._key
        import os

        raw = os.environ.get(self.secret_key_env)
        if not raw:
            raise RuntimeError(
                f"环境变量 {self.secret_key_env} 未设置: 无法加密存储 Secret "
                "(生成 32 字节随机数, base64 编码后设置到环境变量)"
            )
        try:
            key = base64.b64decode(raw)
        except Exception as exc:
            raise RuntimeError(f"{self.secret_key_env} 不是合法的 base64: {exc}") from exc
        if len(key) != 32:
            raise RuntimeError(
                f"{self.secret_key_env} 解码后必须是 32 字节, 实际 {len(key)} 字节"
            )
        self._key = key
        return key

    def _load_cache(self) -> dict[str, dict[str, str]]:
        """从磁盘加载加密的 secrets 字典 (惰性, 缓存)。"""
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = {}
            return self._cache
        try:
            raw = self.path.read_text(encoding="utf-8")
            self._cache = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Secret 文件损坏: {exc}") from exc
        return self._cache

    def _save_cache(self) -> None:
        """把加密的 secrets 字典写回磁盘 (原子替换)。"""
        from isac.utils.fs import atomic_write_text

        cache = self._cache or {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(cache, ensure_ascii=False, indent=2))

    async def get(self, key: str) -> str | None:
        """读取并解密一个 secret。不存在返回 None。"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        cache = self._load_cache()
        entry = cache.get(key)
        if entry is None:
            return None
        try:
            nonce = base64.b64decode(entry["nonce"])
            ciphertext = base64.b64decode(entry["ciphertext"])
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"Secret {key} 加密条目损坏: {exc}") from exc
        aesgcm = AESGCM(self._load_key())
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            raise RuntimeError(f"Secret {key} 解密失败 (密钥不匹配或数据损坏): {exc}") from exc
        return plaintext.decode("utf-8")

    async def set(self, key: str, value: str) -> None:
        """加密写入一个 secret。"""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aesgcm = AESGCM(self._load_key())
        nonce = _generate_nonce()
        ciphertext = aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        cache = self._load_cache()
        cache[key] = {
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        self._save_cache()

    async def delete(self, key: str) -> bool:
        """删除一个 secret; 返回是否删除成功。"""
        cache = self._load_cache()
        if key not in cache:
            return False
        del cache[key]
        self._save_cache()
        return True


def _generate_nonce() -> bytes:
    """生成 12 字节随机 nonce (AES-GCM 推荐 96 位)。"""
    import secrets

    return secrets.token_bytes(12)


# R5: secret: 前缀约定 —— 配置中 api_key 值形如 "secret:<key>" 时经 SecretStore 解密。
SECRET_PREFIX = "secret:"


async def resolve_secret_async(value: str, secret_store: SecretStore | None) -> str:
    """解析 ``secret:<key>`` 前缀的密钥引用, 返回真实明文值。

    - 非 ``secret:`` 前缀 (含明文 / 占位符 / env 覆盖值) 原样返回。
    - ``secret:`` 前缀但 secret_store 为 None (未配置 ISAC_SECRET_KEY env) → 回退
      原值 + warning (不静默降级到明文, 但也不硬阻断 —— 用户可能尚未配置 env)。
    - ``secret:`` 前缀 + store 非 None → ``store.get(key)``; 不存在返回空串 + warning。
    """
    if not value or not value.startswith(SECRET_PREFIX):
        return value
    key = value[len(SECRET_PREFIX) :]
    if secret_store is None:
        import warnings

        warnings.warn(
            f"配置值 {value} 引用 SecretStore 但 ISAC_SECRET_KEY 未配置, 无法解密",
            stacklevel=2,
        )
        return value
    resolved = await secret_store.get(key)
    if resolved is None:
        import warnings

        warnings.warn(f"SecretStore 中未找到 {key}, 该密钥引用将无法使用", stacklevel=2)
        return ""
    return resolved


async def _resolve_secret_field(
    container: Any, field: str, secret_store: SecretStore | None
) -> None:
    """就地解析单个 dict 里某字段的 ``secret:`` 引用 (非 dict/缺字段/非 str 时 no-op)。"""
    if not isinstance(container, dict):
        return
    value = container.get(field)
    if isinstance(value, str):
        container[field] = await resolve_secret_async(value, secret_store)


async def resolve_secrets_in_config(config: dict, secret_store: SecretStore | None) -> None:
    """就地解析 global_config 中所有 ``secret:`` 前缀的密钥引用 (R5)。

    扫描:
    - ``llm.api_key`` + ``llm.multimodal[*].api_key`` (主 LLM / 旧式多模态节);
    - ``multimodal_providers[*].api_key`` (J2 多模态 Provider, register_multimodal_providers
      直接读此键);
    - ``mcp.servers[*].token`` (R3 全局 MCP Server 定义, MCPClient 作为 Bearer 用)。

    Fix-106: 此前仅覆盖 llm.api_key + llm.multimodal[*].api_key, 用户在
    multimodal_providers[] / mcp.servers[].token 写 ``secret:xxx`` 会原样透传给
    Provider/MCPClient (字面 "secret:xxx" 当密钥用 → 注册失败/鉴权恒错)。统一收口。
    在 build_services / register_llm_provider 之前调用, 使同步注册函数拿到明文。
    """
    llm = config.get("llm")
    await _resolve_secret_field(llm, "api_key", secret_store)
    mm = llm.get("multimodal") if isinstance(llm, dict) else None
    if isinstance(mm, list):
        for entry in mm:
            await _resolve_secret_field(entry, "api_key", secret_store)
    mm_providers = config.get("multimodal_providers")
    if isinstance(mm_providers, list):
        for entry in mm_providers:
            await _resolve_secret_field(entry, "api_key", secret_store)
    mcp = config.get("mcp")
    mcp_servers = mcp.get("servers") if isinstance(mcp, dict) else None
    if isinstance(mcp_servers, dict):
        for entry in mcp_servers.values():
            await _resolve_secret_field(entry, "token", secret_store)
