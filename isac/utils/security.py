"""API Key 加密存储 (DEVELOP.md 7.1)。

- 算法: AES-256-GCM
- 密钥来源: 环境变量 ISAC_SECRET_KEY (32 字节，base64 编码)
- 存储位置: data/.secrets.enc
"""

from __future__ import annotations


class SecretStore:
    """敏感信息加密存储。

    [桩] 实现 AES-256-GCM 加解密 + data/.secrets.enc 读写; 禁止明文存储在配置文件或代码中。
    """

    def __init__(self, path: str, secret_key_env: str = "ISAC_SECRET_KEY"):
        self.path = path
        self.secret_key_env = secret_key_env

    async def get(self, key: str) -> str | None:
        """读取并解密一个 secret。不存在返回 None。"""
        raise NotImplementedError("SecretStore.get 尚未实现")

    async def set(self, key: str, value: str) -> None:
        """加密写入一个 secret。"""
        raise NotImplementedError("SecretStore.set 尚未实现")
