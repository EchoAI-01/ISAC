"""AgentInstance: 运行中的 Agent (ARCHITECTURE.md 3.1)。

所有子系统按实例独立组装，不共享可变状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from isac.runtime.config import AgentConfig
from isac.runtime.services import ServiceContainer

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks
    from isac.agent.loop import ISACAgentLoop
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.commands.registry import CommandRegistry
    from isac.core.policy import EnableMatrix
    from isac.gating.system import GatingSystem
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.persona.manager import PersonaManager
    from isac.runtime.progress import ProgressReporter


@dataclass
class AgentInstance:
    """一个运行中的 Agent。"""

    agent_id: str
    config: AgentConfig
    gating: GatingSystem
    prompt_builder: SystemPromptBuilder
    hooks: AgentHooks
    loop: ISACAgentLoop
    memory: MemoryRetrievalPipeline
    persona: PersonaManager
    tools: ToolRegistry
    status: str = "stopped"  # "running" | "stopped" | "error"
    services: ServiceContainer = field(default_factory=ServiceContainer)  # 注入的共享服务 (bus 等)
    # E4 启用矩阵
    enable_matrix: EnableMatrix | None = None
    commands: CommandRegistry | None = None
    # D9: per-session ProgressReporter 缓存 (min_interval_seconds 频控需跨消息生效)。
    progress_reporters: dict[str, ProgressReporter] = field(default_factory=dict)
