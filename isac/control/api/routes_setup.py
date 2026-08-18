"""T3-backend: 首登 setup API (POST /setup 设密码, GET /setup 查状态)。

无认证 (首登态无凭证可认证); CSRF middleware 对无 session cookie 的请求放行。
已设置密码后 POST /setup 返回 409 SETUP_ALREADY_DONE (轮换走 CLI `isac
password reset` 后重新 setup)。

对标 AstrBot password_change_required + /setup 首登向导的后端支撑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from isac.control.setup import SetupManager

from isac.control.setup import MIN_PASSWORD_LENGTH


class SetupRequest(BaseModel):
    """setup 请求体: 密码长度在模型层校验 (短于阈值直接 422, 不进入 manager)。"""

    password: str

    @field_validator("password")
    @classmethod
    def _check_length(cls, v: str) -> str:
        if len(v) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
        return v


def build_router(setup_manager: SetupManager) -> Any:
    """构造 /setup 路由 (无条件挂载, 首登态也要可达)。"""
    from fastapi import APIRouter, HTTPException

    router = APIRouter(tags=["setup"])

    @router.get("/setup")
    async def setup_status() -> dict:
        """返回 setup_required 标志 (前端首登向导据此决定是否进 setup 流程)。"""
        return {"setup_required": setup_manager.is_setup_required}

    @router.post("/setup")
    async def complete_setup(body: SetupRequest) -> dict:
        # Fix-40: 已配静态凭证 (api_token/tokens) 时 setup 通道必须关闭 ——
        # 本端点无认证, 若允许设密码, 攻击者可为自己创建被 auth 层接受的凭证
        # 接管控制面 (即使 setup_state 因新数据目录/CLI reset 而缺失)。
        if getattr(setup_manager, "has_static_credentials", False):
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "SETUP_NOT_ALLOWED",
                    "message": "已配置 api_token/tokens, 认证走静态凭证, setup 通道不可用",
                },
            )
        if not setup_manager.is_setup_required:
            raise HTTPException(
                status_code=409,
                detail={"code": "SETUP_ALREADY_DONE", "message": "首登密码已设置, 轮换请用 isac password reset"},
            )
        setup_manager.complete_setup(body.password)
        return {"status": "ok", "setup_required": False}

    return router
