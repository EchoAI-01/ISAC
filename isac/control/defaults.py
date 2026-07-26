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
    # Q0: 与全局默认一致改 deny (无搜索后端, allow 只会让 LLM 反复调用死工具)
    "web_search": "deny",
    "fetch_history": "allow",
    "switch_chat": "allow",
    "view_forward_message": "allow",
    "wait": "allow",
}

# 受限 commands_allow: 自动化创建 Agent 仅放行安全命令
RESTRICTED_COMMANDS_ALLOW: list[str] = ["focus", "mute", "unmute"]

# CR3-L1: 自动化创建路径 (Admin API / MCP) 不采纳调用方的能力字段, 一律由
# 受限默认值接管 —— 否则持 agent:write 的 Token 可以直接 POST 出一个开 bash、
# 全插件的 Agent, make_restricted_agent_config 形同虚设。
RESTRICTED_CAPABILITY_FIELDS: frozenset[str] = frozenset(
    {"tools_policy", "plugins_allow", "plugins_deny", "commands_allow", "mcp_servers"}
)


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


def restricted_config_from_payload(config: dict) -> AgentConfig:
    """CR3-L1: 校验调用方 payload 后构造受限默认 AgentConfig (自动化创建路径共用)。

    先用 AgentConfig(**config) 做严格校验 —— agent_id 格式非法/未知字段的
    ValueError/TypeError 原样抛出, 由调用方转 400 / JSON-RPC 错误 (与接入受限
    默认之前的行为一致)。能力字段 (RESTRICTED_CAPABILITY_FIELDS) 一律丢弃并
    告警, 由 make_restricted_agent_config 的受限默认值接管; 其余字段
    (persona/gating/llm/trigger_words/memory_namespace 等) 原样透传。

    需要放宽能力的 Agent 走后续 PATCH /agents/{id} 或插件矩阵接口显式授予
    (有审计), 而不是在创建时静默带入。
    """
    requested = AgentConfig(**config)
    dropped = sorted(k for k in RESTRICTED_CAPABILITY_FIELDS if k in config)
    if dropped:
        logger.warning(
            "自动化创建 Agent 的能力字段被受限默认值覆盖 (CR3-L1)",
            agent_id=requested.agent_id,
            dropped_fields=dropped,
        )
    extra = {
        k: v
        for k, v in config.items()
        if k not in RESTRICTED_CAPABILITY_FIELDS and k not in ("agent_id", "display_name")
    }
    return make_restricted_agent_config(requested.agent_id, requested.display_name, extra=extra)


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
