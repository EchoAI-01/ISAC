"""write_file 工具: 写入项目目录内的文件 (restricted 策略)。

路径白名单: 相对 services["workspace_root"] 解析, 禁止绝对路径与 .. 越权。
"""

from __future__ import annotations

from pathlib import Path

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

MAX_WRITE_BYTES = 256 * 1024  # 256KB 上限


class WriteFileTool(Tool):
    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "写入项目目录内的文件"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对 workspace_root 的路径"},
                "content": {"type": "string", "description": "文件内容"},
                "append": {"type": "boolean", "description": "是否追加 (默认 False 覆盖)", "default": False},
            },
            "required": ["path", "content"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        workspace_root = context.services.get("workspace_root")
        if not workspace_root:
            return ToolResult(content="未配置 workspace_root, write_file 不可用。", is_error=True)

        raw_path = str(context.args.get("path", "") or "").strip()
        content = str(context.args.get("content", "") or "")
        if not raw_path:
            return ToolResult(content="write_file 缺少 path。", is_error=True)
        if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
            return ToolResult(content=f"写入内容超过 {MAX_WRITE_BYTES} 字节上限。", is_error=True)

        safe_path = _resolve_safe(workspace_root, raw_path)
        if safe_path is None:
            return ToolResult(
                content=f"路径 {raw_path} 越权或不在 workspace_root 内, 已拒绝。",
                is_error=True,
            )

        append = bool(context.args.get("append", False))
        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with safe_path.open(mode, encoding="utf-8") as fp:
                fp.write(content)
        except Exception as exc:
            return ToolResult(content=f"写入失败: {exc}", is_error=True)
        return ToolResult(content=f"已{'追加' if append else '写入'} {len(content)} 字符到 {raw_path}")


def _resolve_safe(workspace_root: str, raw_path: str) -> Path | None:
    """同 read_file._resolve_safe: 拒绝绝对路径与 .. 越权。"""
    if not raw_path or raw_path.startswith("/"):
        return None
    root = Path(workspace_root).resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
