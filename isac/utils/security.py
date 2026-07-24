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
