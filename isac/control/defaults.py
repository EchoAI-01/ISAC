"""控制面安全默认配置 (DEVELOP.md 7.4)。

自动化创建 Agent (经 MCP / API trigger / webhooks) 时使用受限默认配置,
避免默认开放高危能力 (如 bash / write_file / 任意 plugins_allow)。

策略:
- tools_policy 默认 deny bash, restricted read_file/write_file/task
- plugins_allow 限定 ["*"] 但实际由 EnableMatrix 过滤; 自动化场景 deny 全部外部插件
- commands_allow 仅放行安全命令 (focus/mute/unmute)
- mcp_servers 默认空 (不连接任何外部 MCP Server)
- memory_namespace 默认 = agent_id (独立记忆)
"""

from __future__ import annotations

from isac.runtime.config import AgentConfig
from isac.utils.logger import get_logger

logger = get_logger(__name__)


# 受限 tools_policy: 自动化创建 Agent 时的默认工具权限
# - bash: deny (shell 命令默认禁用)
# - read_file/write_file: restricted (需注入 workspace_root 后端)
# - web_search: allow (只读)
# - task: deny (子 Agent 委派默认禁用, 避免无限递归)
# - send_emoji/send_image: allow (社交能力)
# - query_memory/query_person_profile: allow
# - ask_agent: restricted (需配置 Link)
# - fetch_history/switch_chat/view_forward_message/wait: allow
RESTRICTED_TOOLS_POLICY: dict[str, str] = {
    "bash": "deny",
    "read_file": "restricted",
    "write_file": "restricted",
    "task": "deny",
    "ask_agent": "restricted",
    "send_emoji": "allow",
    "send_image": "allow",
    "query_memory": "allow",
    "query_person_profile": "allow",
    "web_search": "allow",
    "fetch_history": "allow",
    "switch_chat": "allow",
    "view_forward_message": "allow",
    "wait": "allow",
}

# 受限 commands_allow: 自动化创建 Agent 仅放行安全命令
RESTRICTED_COMMANDS_ALLOW: list[str] = ["focus", "mute", "unmute"]


def make_restricted_agent_config(
    agent_id: str,
    display_name: str = "",
    *,
    extra: dict | None = None,
) -> AgentConfig:
    """构造自动化创建 Agent 的受限默认配置。

    自动化场景 (Admin API / MCP / Webhooks trigger) 调用此函数而非直接 new AgentConfig,
    确保新 Agent 不会默认开放高危能力。

    Args:
        agent_id: Agent ID
        display_name: 展示名
        extra: 额外覆盖字段 (如 trigger_words/memory_namespace/llm)
    """
    config = AgentConfig(
        agent_id=agent_id,
        display_name=display_name or f"Agent-{agent_id}",
        enabled=True,
        tools_policy=dict(RESTRICTED_TOOLS_POLICY),
        commands_allow=list(RESTRICTED_COMMANDS_ALLOW),
        plugins_allow=[],  # 自动化场景默认禁用所有外部插件
        plugins_deny=["*"],  # 显式 deny 全部
        mcp_servers=[],  # 默认不连接外部 MCP Server
    )
    if extra:
        for key, value in extra.items():
            if hasattr(config, key):
                setattr(config, key, value)
            else:
                logger.warning("自动化创建 Agent 收到未知字段, 忽略", field=key)
    logger.info(
        "已构造受限默认 Agent 配置",
        agent_id=agent_id,
        tools_deny=[k for k, v in RESTRICTED_TOOLS_POLICY.items() if v == "deny"],
        commands_allow=RESTRICTED_COMMANDS_ALLOW,
    )
    return config


def is_safe_default_host(host: str) -> bool:
    """检查控制面绑定地址是否安全 (仅 127.0.0.1 / localhost)。"""
    if not host:
        return False
    return host in ("127.0.0.1", "localhost", "::1")


def enforce_safe_host(host: str, default: str = "127.0.0.1") -> str:
    """若 host 不安全, 退回 default (127.0.0.1)。"""
    if is_safe_default_host(host):
        return host
    logger.warning("控制面绑定非安全地址, 强制回退到 127.0.0.1", requested=host)
    return default
