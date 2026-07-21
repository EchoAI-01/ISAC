"""AgentInstance: 运行中的 Agent (ARCHITECTURE.md 3.1)。

所有子系统按实例独立组装，不共享可变状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from isac.runtime.config import AgentConfig

if TYPE_CHECKING:
    from isac.agent.hooks import AgentHooks
    from isac.agent.loop import ISACAgentLoop
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.gating.system import GatingSystem
    from isac.memory.pipeline import MemoryRetrievalPipeline
    from isac.persona.manager import PersonaManager


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
    services: dict[str, Any] = field(default_factory=dict)  # 注入的共享服务 (bus 等)
