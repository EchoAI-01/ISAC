"""ISAC WebUI 管理面板 (I1, ARCHITECTURE.md 3.9)。

FastAPI 静态托管 + Vanilla JS, 调用 G1 Admin API 管理 Agent/路由/Link/记忆。
不依赖 Vue 构建工具链, 单页 HTML + fetch 调用。

启动: 控制面已运行时, 访问 http://127.0.0.1:8765/ui/

**DEPRECATED (FE1, 2026-08-16)**: 本静态托管 WebUI 在前后端分离后由独立前端
项目 (F1-F4, DEVELOPMENT_PLAN.md §四 FE) 取代。迁移期保留可用 (control/webui/
仍随包发布, /ui 仍挂载); F2 十域页面迁移完成并验证后, 本模块与 /ui 挂载将移除。
新功能不要加到本 WebUI, 改在独立前端项目实现 (消费 /api/v1 + SSE 契约)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

WEBUI_DIR = Path(__file__).parent  # 与本文件同目录的 index.html / app.js


def mount_webui(app: Any, *, prefix: str = "/ui", api_token: str = "") -> None:
    """把 WebUI 静态资源挂载到 FastAPI app。

    Args:
        app: FastAPI 实例
        prefix: URL 前缀 (默认 /ui)
        api_token: 用于前端 fetch Bearer 认证 (会注入到 HTML 中)
    """
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    index_path = WEBUI_DIR / "index.html"
    app_js_path = WEBUI_DIR / "app.js"

    @app.get(prefix + "/", include_in_schema=False)
    async def index_page() -> FileResponse:
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="WebUI index.html 未找到")
        return FileResponse(index_path, media_type="text/html")

    @app.get(prefix + "/app.js", include_in_schema=False)
    async def app_js() -> FileResponse:
        if not app_js_path.exists():
            raise HTTPException(status_code=404, detail="WebUI app.js 未找到")
        return FileResponse(app_js_path, media_type="application/javascript")


def get_webui_html() -> str:
    """返回 WebUI index.html 内容 (供 API 返回或调试)。"""
    index_path = WEBUI_DIR / "index.html"
    if not index_path.exists():
        return ""
    return index_path.read_text(encoding="utf-8")
