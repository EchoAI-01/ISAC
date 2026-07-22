"""read_file 工具: 读取项目目录内的文件 (restricted 策略)。

路径白名单: 相对 services["workspace_root"] 解析, 禁止绝对路径与 .. 越权。
"""

from __future__ import annotations

from pathlib import Path

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

MAX_READ_BYTES = 64 * 1024  # 64KB 上限, 避免一次读入巨大文件
MAX_READ_LINES = 2000


class ReadFileTool(Tool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取项目目录内的文件内容"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对 workspace_root 的路径"},
                "start_line": {"type": "integer", "description": "起始行 (1-based, 默认 1)", "default": 1},
                "end_line": {"type": "integer", "description": "结束行 (含, 默认 2000)", "default": 2000},
            },
            "required": ["path"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        workspace_root = context.services.get("workspace_root")
        if not workspace_root:
            return ToolResult(content="未配置 workspace_root, read_file 不可用。", is_error=True)

        raw_path = str(context.args.get("path", "") or "").strip()
        if not raw_path:
            return ToolResult(content="read_file 缺少 path。", is_error=True)

        safe_path = _resolve_safe(workspace_root, raw_path)
        if safe_path is None:
            return ToolResult(
                content=f"路径 {raw_path} 越权或不在 workspace_root 内, 已拒绝。",
                is_error=True,
            )
        if not safe_path.is_file():
            return ToolResult(content=f"{raw_path} 不存在或不是文件。", is_error=True)

        start_line = max(1, int(context.args.get("start_line", 1) or 1))
        end_line = max(start_line, int(context.args.get("end_line", MAX_READ_LINES) or MAX_READ_LINES))

        try:
            data = safe_path.read_bytes()
            if len(data) > MAX_READ_BYTES:
                data = data[:MAX_READ_BYTES]
            text = data.decode("utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(content=f"读取失败: {exc}", is_error=True)

        lines = text.splitlines()
        clipped = lines[max(0, start_line - 1) : end_line]
        body = "\n".join(f"{i + start_line:>4}  {line}" for i, line in enumerate(clipped))
        return ToolResult(content=f"【{raw_path} (lines {start_line}-{start_line + len(clipped) - 1})】\n{body}")


def _resolve_safe(workspace_root: str, raw_path: str) -> Path | None:
    """把 raw_path 安全解析到 workspace_root 内, 拒绝绝对路径与 .. 越权。"""
    if not raw_path or raw_path.startswith("/"):
        return None
    root = Path(workspace_root).resolve()
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
