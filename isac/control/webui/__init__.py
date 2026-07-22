"""ISAC WebUI 管理面板 (I1, ARCHITECTURE.md 3.9)。

FastAPI 静态托管 + Vanilla JS, 调用 G1 Admin API 管理 Agent/路由/Link/记忆。
不依赖 Vue 构建工具链, 单页 HTML + fetch 调用。

启动: 控制面已运行时, 访问 http://127.0.0.1:8765/ui/
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
    from fastapi.staticfiles import StaticFiles

    index_path = WEBUI_DIR / "index.html"

    @app.get(prefix + "/", include_in_schema=False)
    async def index_page() -> FileResponse:
        if not index_path.exists():
            raise HTTPException(status_code=404, detail="WebUI index.html 未找到")
        return FileResponse(index_path, media_type="text/html")

    # 其他静态资源 (CSS/JS/图片)
    app.mount(prefix, StaticFiles(directory=WEBUI_DIR), name="isac_webui")


def get_webui_html() -> str:
    """返回 WebUI index.html 内容 (供 API 返回或调试)。"""
    index_path = WEBUI_DIR / "index.html"
    if not index_path.exists():
        return ""
    return index_path.read_text(encoding="utf-8")
