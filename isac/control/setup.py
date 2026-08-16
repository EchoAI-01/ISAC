"""T3-backend: 首登强制设密码状态机 (对标 AstrBot password_change_required)。

首启 (无 api_token/tokens/env 且 setup_state 无 password_hash) → 控制面进入
"待设置"态: admin 端点返回 428 SETUP_REQUIRED, 仅 /setup 与 /health 可用。
POST /api/v1/setup {password} 设置密码 (PBKDF2-HMAC-SHA256 哈希存储, 禁止明文,
禁止硬编码默认密码)。设置后密码成为有效 Bearer Token (auth dependency 比对
hash)。CLI `isac password reset` 删 setup_state 回到首登态。

设计要点:
- 密码永不落明文: 只存 "alg$salt_b64$hash_b64" (PBKDF2 20 万次, 对标 OWASP 2023)。
- 状态文件 data/control/setup_state.json, 原子写 (与 K4 配置持久化同模式)。
- Fix-40: 已配静态凭证 (api_token/tokens) 时 setup 不再必需且 POST /setup 拒绝 ——
  此前 is_setup_required 只看自身 hash, 而 POST /setup 无认证: 已配凭证但
  setup_state 缺失 (新数据目录 / CLI reset 后) 时, 未认证攻击者可经 POST /setup
  设置自己的密码并被 auth 层接受 (is_password_valid), 直接接管控制面。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path

MIN_PASSWORD_LENGTH = 8
_PBKDF2_ITERATIONS = 200_000


class SetupManager:
    """首登密码状态机 (T3-backend)。

    Args:
        state_path: setup_state.json 路径 (默认 data/control/setup_state.json)。
        static_credentials_configured: 是否已配置静态凭证 (api_token/tokens[])。
            Fix-40: 已配凭证时 setup 不再必需, complete_setup 拒绝 (防未认证接管)。
    """

    def __init__(
        self,
        state_path: str = "data/control/setup_state.json",
        *,
        static_credentials_configured: bool = False,
    ) -> None:
        self.state_path = Path(state_path)
        self._hash: str | None = None
        self._has_static_credentials = static_credentials_configured
        self._load()

    def _load(self) -> None:
        """从状态文件加载 password_hash (文件缺失/损坏视为未设置)。"""
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            self._hash = data.get("password_hash") or None
        except (OSError, ValueError):
            self._hash = None

    @property
    def has_static_credentials(self) -> bool:
        """是否已配置静态凭证 (api_token/tokens[]), Fix-40 供路由层细化错误码。"""
        return self._has_static_credentials

    @property
    def is_setup_required(self) -> bool:
        """是否整体需要首登 setup: 密码未设置 **且** 未配置静态凭证 (Fix-40)。"""
        return self._hash is None and not self._has_static_credentials

    def is_password_valid(self, candidate: str | None) -> bool:
        """恒定时间校验候选密码是否匹配已设置的 hash; 未设置或格式错返回 False。"""
        if not candidate or not self._hash:
            return False
        try:
            alg, salt_b64, hash_b64 = self._hash.split("$")
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
        except (ValueError, TypeError):
            return False
        actual = hashlib.pbkdf2_hmac(alg, candidate.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return hmac.compare_digest(actual, expected)

    def complete_setup(self, password: str) -> None:
        """设置首登密码 (PBKDF2 哈希落盘); 密码过短抛 ValueError。

        已设置过密码时重复调用会覆盖 (用于密码轮换, 但生产轮换建议走 CLI reset
        + 重新 setup 以避免在线覆盖的竞态)。Fix-40: 已配静态凭证时拒绝 (PermissionError),
        防止未认证调用方经本方法给自己创建有效凭证。
        """
        if self._has_static_credentials:
            raise PermissionError("已配置 api_token/tokens, setup 通道关闭")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        self._hash = (
            f"sha256${base64.b64encode(salt).decode('ascii')}${base64.b64encode(digest).decode('ascii')}"
        )
        self._save()

    def reset(self) -> None:
        """清除首登密码 (回到首登态); CLI `isac password reset` 调用。"""
        self._hash = None
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    def _save(self) -> None:
        """原子写状态文件 (tmp + replace, 与 K4 配置持久化同模式)。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps({"password_hash": self._hash}), encoding="utf-8")
        tmp.replace(self.state_path)
