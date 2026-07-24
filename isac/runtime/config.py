"""AgentConfig: 单个 Agent 的独立配置 (SPECIFICATION.md 1.6)。

配置层次 (SPECIFICATION.md 3.3): 全局 config.jsonc ← Agent 级覆盖 ← 环境变量/CLI。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import json5

    _loads = json5.loads
except ImportError:  # pragma: no cover
    _loads = json.loads

AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass
class AgentConfig:
    """单个 Agent 的独立配置 (data/agents/<agent_id>/config.jsonc)"""

    agent_id: str
    display_name: str = ""
    enabled: bool = True

    # 人格 / 门控: 覆盖全局配置的子集
    persona: dict[str, Any] = field(default_factory=dict)
    gating: dict[str, Any] = field(default_factory=dict)

    # 记忆命名空间: 默认 = agent_id; "shared" 表示跨 Agent 共享
    memory_namespace: str = ""

    # LLM: None = 使用全局默认 Provider; 否则该 Agent 独立 Provider 配置
    llm: dict[str, Any] | None = None

    # 路由触发词: 消息以这些词开头时路由到本 Agent
    trigger_words: list[str] = field(default_factory=list)

    # 能力开关: 插件 / 工具 / 命令 / MCP, 按 Agent 独立配置
    plugins_allow: list[str] = field(default_factory=lambda: ["*"])
    plugins_deny: list[str] = field(default_factory=list)
    tools_policy: dict[str, str] = field(default_factory=dict)  # 覆盖全局工具权限
    commands_allow: list[str] = field(default_factory=lambda: ["*"])
    mcp_servers: list[str] = field(default_factory=list)  # 允许使用的 MCP Server 名

    def __post_init__(self) -> None:
        """校验 agent_id，避免其被用于拼接文件路径时发生目录穿越 (SPECIFICATION.md 3.3)。"""
        if not AGENT_ID_PATTERN.match(self.agent_id):
            raise ValueError(
                f"agent_id 非法: {self.agent_id!r}，只允许 1-64 位字母/数字/下划线/短横线"
            )

    @property
    def effective_memory_namespace(self) -> str:
        return self.memory_namespace or self.agent_id


def load_agent_config(path: str | Path) -> AgentConfig:
    """从 JSONC 文件加载 Agent 配置。"""
    raw = _loads(Path(path).read_text(encoding="utf-8"))
    return AgentConfig(**{k: v for k, v in raw.items() if k in AgentConfig.__dataclass_fields__})


def save_agent_config(path: str | Path, config: AgentConfig) -> None:
    """保存 Agent 配置到 JSONC 文件 (原子替换, K4)。"""
    file_path = Path(path)
    content = json.dumps(asdict(config), ensure_ascii=False, indent=2)
    from isac.utils.fs import atomic_write_text

    atomic_write_text(file_path, content)
    logger.info("Agent 配置已保存", agent_id=config.agent_id, path=str(file_path))
