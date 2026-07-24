"""bash 工具: 受限 shell 执行 (默认禁用, DEVELOP.md 7.3)。

仅当 services["bash_allowlist"] 注入时可用; 命令必须能在白名单内匹配通过。
"""

from __future__ import annotations

import asyncio
import shlex

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
MAX_OUTPUT_CHARS = 4000


class BashTool(Tool):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "执行受白名单限制的 shell 命令 (默认禁用, 需在配置中显式启用)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "命令"},
                "timeout": {"type": "integer", "description": "超时秒数 (默认 10)", "default": DEFAULT_TIMEOUT_SECONDS},
            },
            "required": ["command"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """执行受白名单限制的 shell 命令 (默认禁用, 需在配置中显式启用)。"""
        allowlist = context.services.get("bash_allowlist")
        if not allowlist:
            return ToolResult(content="未配置 bash_allowlist, bash 工具不可用。", is_error=True)

        raw_command = str(context.args.get("command", "") or "").strip()
        if not raw_command:
            return ToolResult(content="bash 缺少 command。", is_error=True)

        try:
            tokens = shlex.split(raw_command)
        except ValueError as exc:
            return ToolResult(content=f"命令解析失败: {exc}", is_error=True)
        if not tokens:
            return ToolResult(content="bash command 为空。", is_error=True)

        guard_error = self._validate_command(raw_command, tokens, allowlist)
        if guard_error is not None:
            return guard_error

        timeout = max(1, int(context.args.get("timeout", DEFAULT_TIMEOUT_SECONDS) or DEFAULT_TIMEOUT_SECONDS))
        return await self._run(tokens, timeout)

    @staticmethod
    def _validate_command(
        raw_command: str, tokens: list[str], allowlist
    ) -> ToolResult | None:
        """返回 ToolResult 表示拒绝, 返回 None 表示通过。"""
        # 先拒绝 shell 元字符 (避免 shlex 把 ls; 解析成 ls; 子命令)
        if any(tok in raw_command for tok in ("&&", "||", "|", ";", ">", "<", "`", "$")):
            return ToolResult(
                content="bash 命令不允许使用 shell 元字符 (&&/||/|/;/>/`/$ 等)。",
                is_error=True,
            )
        # 白名单匹配: tokens[0] 必须在 allowlist 中
        if tokens[0] not in allowlist:
            return ToolResult(
                content=f"命令 {tokens[0]} 不在白名单 {sorted(allowlist)} 内, 已拒绝。",
                is_error=True,
            )
        return None

    async def _run(self, tokens: list[str], timeout_seconds: int) -> ToolResult:
        """实际执行命令并格式化输出。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *tokens,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            else:
                # K7: kill 后必须 await wait() 等待进程退出回收, 否则留下僵尸进程
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    logger.warning("bash 子进程 kill 后 5 秒仍未退出", tokens=tokens)
            return ToolResult(content=f"命令超时 (> {timeout_seconds}s), 已终止。", is_error=True)
        except Exception as exc:
            return ToolResult(content=f"命令执行失败: {exc}", is_error=True)

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + f"...[truncated, total {len(out)} chars]"
        parts = [f"exit={proc.returncode}", f"stdout:\n{out}"]
        if err.strip():
            parts.append(f"stderr:\n{err}")
        return ToolResult(content="\n".join(parts))
