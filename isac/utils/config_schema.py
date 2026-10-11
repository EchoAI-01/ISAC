"""配置 schema 校验 (SPECIFICATION.md 3.2)。

在 load_config 合并 (默认值 + 文件 + 环境变量 + 迁移) 之后做一层轻量校验:
- **宽松 (extra="allow")**: 配置项繁多且大量动态 (multimodal_providers[] 任意 kind、
  channels 任意平台), schema 只对已知关键字段严格校验, 未知字段一律放行, 避免每加
  一个配置键就报错、schema 变成维护负担。
- **对明确的配置错误硬失败**: control.port 越界/非法类型等 → 抛 ConfigValidationError
  (清晰指出哪个字段), 早于运行期崩溃。
- **对安全隐患高声告警 (fail-closed 提醒, 非阻塞)**: control.enabled=true 但既无
  api_token 也无 tokens[] 时, 所有控制面认证被静默禁用 (评审 R4/X2 的根因)。此处
  记 CRITICAL 日志把"静默"变"高声", 不硬阻断启动 (避免破坏本机开发无 token 调试)。

validate_config 返回**原 config dict 不变** (只校验、不改结构), 保持 load_config 语义。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigValidationError(ValueError):
    """配置校验失败 (非法端口/类型等)。启动期抛出, 消息指明失败字段。"""


# Fix-30: control.* 字段显式 JSON null 等价于"未配置"。此前这些字段类型不接受
# None (如 tokens: list[Any]), 手工维护/工具生成的 JSONC 里写 "tokens": null
# 会被 pydantic 拒绝并在启动期抛 ConfigValidationError 崩溃——而历史行为 (加
# schema 校验之前) 对这些字段一律按 falsy/未配置处理, 完全无害。
_CONTROL_FIELD_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "host": "127.0.0.1",
    "allow_external_host": False,
    "port": 8765,
    "api_token": "",
    "tokens": [],
    "cors": {},
    "setup_enabled": True,
}


class CorsConfig(BaseModel):
    """前后端分离的 CORS 配置 (FE1, DEVELOPMENT_PLAN.md §四 FE1)。

    origins 默认空 = 不加 CORSMiddleware (同源部署或纯 API 网关场景, 零行为变化)。
    配置非空时, 对这些前端 origin 放开跨源请求 + allow_credentials=True (供分离
    部署的 WebUI 用 Session Cookie); 此时 Session Cookie 的 SameSite 从 strict
    降为 lax (跨源可带)。生产推荐同源反代 (前端与 API 同 origin), 无需配置本字段。
    """

    model_config = ConfigDict(extra="allow")

    origins: list[str] = Field(default_factory=list)
    allow_credentials: bool = True


class ControlConfig(BaseModel):
    """控制面配置的受校验字段 (extra="allow" 放行 workflow/plugins/agents_dir 等其余键)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    host: str = "127.0.0.1"
    allow_external_host: bool = False
    port: int = Field(default=8765, ge=1, le=65535)
    api_token: str = ""
    tokens: list[Any] = Field(default_factory=list)
    cors: CorsConfig = Field(default_factory=CorsConfig)
    setup_enabled: bool = True

    @field_validator(
        "enabled", "host", "allow_external_host", "port", "api_token", "tokens", "cors", "setup_enabled",
        mode="before",
    )
    @classmethod
    def _none_means_unset(cls, v: Any, info: ValidationInfo) -> Any:
        """显式 null 等价于该字段未配置, 落回默认值; 其余非法值 (类型错/越界)
        原样传给标准校验, 仍按预期抛 ConfigValidationError, 不受本 fix 影响。"""
        if v is None:
            return _CONTROL_FIELD_DEFAULTS[str(info.field_name)]
        return v


# ── N4 API 基线: 全量顶层节模型 (宽松建模, 仅供 /config/schema 表单驱动) ─────
# 设计约束: 不新增硬校验 (唯一保留 control.port 的 ge/le 与既有语义), 子字段只给
# 类型 + 默认 + description; 深层嵌套 (memory.embedding / control.plugins.isolation
# 等) 用 dict[str, Any] 兜底 —— 前端渲染一级表单, 深节继续 JSON 编辑。


class LoggingConfig(BaseModel):
    """日志与可观测性 (docs/LOGGING.md)。"""

    model_config = ConfigDict(extra="allow")

    level: str = Field(default="info", description="全局级别 debug|info|warning|error")
    format: str = Field(default="console", description="console (开发彩色) | json (生产采集)")
    per_module: dict[str, str] = Field(default_factory=dict, description="按模块前缀单独设级")


class LLMConfig(BaseModel):
    """主 LLM (文生文): 通用 OpenAI 兼容端点。"""

    model_config = ConfigDict(extra="allow")

    provider: str = Field(default="openai", description="Provider 标识")
    api_key: str = Field(
        default="", description="API Key; 生产可填 secret:<key> 引用 SecretStore (R5)"
    )
    base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI 兼容 base URL")
    model: str = Field(default="", description="模型名 (如 gpt-4o-mini)")
    cost_tier: str = Field(default="", description="U7 成本档 free|low|standard|high (缺省按快照)")
    latency_tier: str = Field(default="", description="U7 延迟档 fast|standard|slow")
    model_family: str = Field(default="", description="prompt 变体的模型族名 (缺省按模型名前缀推断)")


class ModelRoutingConfig(BaseModel):
    """U7 category 路由: 按任务类型选模型链。"""

    model_config = ConfigDict(extra="allow")

    categories: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="四类画像覆盖 (qa/creative/tool_heavy/chat; operation/cost_ceiling/latency_target/requires_tools)",
    )


class MemoryConfig(BaseModel):
    """记忆子系统 (Q1 起默认开启, 纯 SQLite 零外部依赖)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="false 时关闭记忆 (检索/注入/写入回路全停)")
    embedding: dict[str, Any] = Field(
        default_factory=dict,
        description="稠密召回配置 (api_key+model 时启用; dimension 必须与模型输出一致)",
    )
    reranker: dict[str, Any] = Field(default_factory=dict, description="重排配置 (Cohere/Jina 协议)")
    graph_recall: dict[str, Any] = Field(default_factory=dict, description="S3 图谱召回 (默认关闭)")
    consolidation: dict[str, Any] = Field(
        default_factory=dict, description="S2 后台整合 (去重/剪枝/画像归纳, 默认关闭)"
    )


class SessionConfig(BaseModel):
    """U1 事件溯源会话内核。"""

    model_config = ConfigDict(extra="allow")

    history: dict[str, Any] = Field(
        default_factory=lambda: {"enabled": True, "window_turns": 10, "budget_tokens": None},
        description="滑动窗口历史 (enabled/window_turns/budget_tokens)",
    )
    compression: dict[str, Any] = Field(
        default_factory=lambda: {
            "enabled": False, "trigger_events": 60,
            "keep_recent_messages": 20, "min_compress_messages": 6,
        },
        description="会话压缩 (阶段3-2 M2, 默认关闭)",
    )


class GatingConfig(BaseModel):
    """U3 门控策略化 (Agent 级 AgentConfig.gating 可覆盖)。"""

    model_config = ConfigDict(extra="allow")

    strategy: str = Field(default="keywords", description="off | keywords | llm-judge | hybrid")
    locale: str = Field(default="zh_CN", description="门控词表语言 (zh_CN/en_US)")
    reply_necessity_threshold: float = Field(default=80, description="回复必要性阈值 (0-100)")
    weights: dict[str, Any] = Field(default_factory=dict, description="评分权重覆盖")
    markers: dict[str, Any] = Field(default_factory=dict, description="question/request/consult 词表覆盖")
    llm_judge_max_per_minute: int = Field(default=10, description="llm-judge 频率上限 (成本防护)")
    hybrid_escalate_band: float = Field(default=20, description="hybrid 档升级判定带宽")


class ConversationConfig(BaseModel):
    """P1 拟人化会话运行时 (默认关闭 = 零行为变化)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=False, description="总开关 (debounce/打断/主动任务)")
    debounce_seconds: float = Field(default=1.5, description="静默合并窗口秒数 (0 = 不合并)")
    max_interrupts_per_turn: int = Field(default=1, description="单轮最多被打断次数")
    proactive: dict[str, Any] = Field(
        default_factory=dict, description="主动任务调度 (min_interval/poll_interval/各生产者开关)"
    )


class PersonaConfig(BaseModel):
    """全局人格 (Q2, Agent 级可覆盖)。"""

    model_config = ConfigDict(extra="allow")

    description: str = Field(default="", description="人格描述 (空 = 框架默认身份文案)")


class IdentityConfig(BaseModel):
    """S4 跨平台身份归一 (默认关闭)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=False, description="启用 IdentityResolver 归一")
    heuristic_enabled: bool = Field(default=False, description="昵称启发式匹配 (低置信, 默认关)")


class TenancyConfig(BaseModel):
    """多租户隔离 (O1/R6, 默认单租户)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=False, description="启用租户隔离 + 租户控制面")
    organization_id: str = Field(default="default", description="组织 ID (记忆命名空间前缀)")
    tenant_id: str = Field(default="default", description="租户 ID")


class ArtifactsConfig(BaseModel):
    """制品存储 (本地 FS, sha256 分桶)。"""

    model_config = ConfigDict(extra="allow")

    ttl_days: int = Field(default=7, description="制品 TTL 天数 (sweep 周期清理)")


class ToolsConfig(BaseModel):
    """CLI 工具后端 (R3) + ask 档审批 (U5)。"""

    model_config = ConfigDict(extra="allow")

    bash_allowlist: list[str] = Field(
        default_factory=list, description="bash 允许的命令前缀 (默认空 = 禁止所有命令)"
    )
    approval: dict[str, Any] = Field(
        default_factory=lambda: {"timeout_seconds": 300},
        description="ask 档人工审批 (timeout_seconds 超时 fail-closed)",
    )


class McpConfig(BaseModel):
    """全局 MCP Server 定义 (R3)。"""

    model_config = ConfigDict(extra="allow")

    servers: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="server 名 → 定义 (transport: stdio|http; command/args/env 或 url/token)",
    )


class AlertingConfig(BaseModel):
    """监控告警 (I5, 规划位: 当前生产未消费本节)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=True, description="告警总开关")
    check_interval_seconds: int = Field(default=30, description="检查间隔")
    webhook_url: str = Field(default="", description="告警推送 webhook (SSRF 校验)")


class ObservabilityConfig(BaseModel):
    """J1 计量 (用量与成本)。"""

    model_config = ConfigDict(extra="allow")

    usage: dict[str, Any] = Field(
        default_factory=lambda: {"enabled": False, "flush_interval_seconds": 30},
        description="用量计量 (enabled/flush_interval_seconds)",
    )


class SubagentConfig(BaseModel):
    """J4 SubAgent (默认关闭)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=False, description="SubAgent 总开关")


class ISACConfig(BaseModel):
    """顶层配置的受校验字段 (N4 API 基线缺口修复: 显式覆盖全量 21 个顶层键)。

    extra="allow" 保持宽松; 各节模型只做**类型宽松**建模 (子字段给类型 + 默认 +
    description 供 /api/v1/config/schema 前端表单驱动), 不新增任何硬校验 —— 现有
    合法配置零行为变化。此前仅 debug/log_level/control 3 键建模, 前端拿到的
    schema 覆盖 3/21 键, F2 配置编辑页无法据此渲染。
    """

    model_config = ConfigDict(extra="allow")

    debug: bool = Field(default=False, description="调试模式 (等价 logging.level=debug)")
    bot_id: str = Field(default="", description="Bot 自身平台 ID (适配器自过滤/私聊提及判定)")
    log_level: str = Field(default="info", description="全局日志级别 (logging.level 的简化写法)")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="日志与可观测性")
    llm: LLMConfig = Field(default_factory=LLMConfig, description="主 LLM (OpenAI 兼容 chat/completions)")
    model_routing: ModelRoutingConfig = Field(
        default_factory=ModelRoutingConfig, description="U7 category 路由 (delegate_task 按类型选模型链)"
    )
    multimodal_providers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="J2 多模态 Provider 数组 (kind: image_gen/stt/tts/embed/vision/rerank/video_gen)",
    )
    memory: MemoryConfig = Field(
        default_factory=MemoryConfig, description="记忆子系统 (SQLite + FTS/BM25 + 可选向量/图谱)"
    )
    session: SessionConfig = Field(
        default_factory=SessionConfig, description="U1 事件溯源会话内核 (滑窗历史/压缩)"
    )
    gating: GatingConfig = Field(
        default_factory=GatingConfig, description="U3 门控策略化 (off/keywords/llm-judge/hybrid)"
    )
    conversation: ConversationConfig = Field(
        default_factory=ConversationConfig, description="P1 拟人化会话运行时 (debounce/打断/主动任务)"
    )
    persona: PersonaConfig = Field(default_factory=PersonaConfig, description="全局人格 (Agent 级 persona 可覆盖)")
    identity: IdentityConfig = Field(default_factory=IdentityConfig, description="S4 跨平台身份归一")
    tenancy: TenancyConfig = Field(default_factory=TenancyConfig, description="多租户隔离 (O1/R6)")
    artifacts: ArtifactsConfig = Field(default_factory=ArtifactsConfig, description="制品存储 (本地 FS, sha256 分桶)")
    control: ControlConfig = Field(default_factory=ControlConfig, description="控制面 (G1 Admin API)")
    tools: ToolsConfig = Field(default_factory=ToolsConfig, description="CLI 工具后端 (bash 白名单/ask 档审批)")
    mcp: McpConfig = Field(default_factory=McpConfig, description="全局 MCP Server 定义 (R3)")
    channels: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Channel 适配器 (onebot/telegram/discord/feishu/qq_official/wechat/webchat)",
    )
    alerting: AlertingConfig = Field(default_factory=AlertingConfig, description="监控告警 (I5, 规划位)")
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig, description="J1 计量 (用量与成本)")
    subagent: SubagentConfig = Field(default_factory=SubagentConfig, description="J4 SubAgent")

    @field_validator(
        "logging", "llm", "model_routing", "memory", "session", "gating", "conversation", "persona",
        "identity", "tenancy", "artifacts", "control", "tools", "mcp", "channels", "alerting",
        "observability", "subagent",
        mode="before",
    )
    @classmethod
    def _none_section_means_unset(cls, v: Any) -> Any:
        """顶层任意节显式 null 等价于未配置该节 (退化成全默认), 与 Fix-30 的
        "control": null 语义一致 —— 手工维护/工具生成的 JSONC 写 null 不崩溃。"""
        if v is None:
            return {}
        return v


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """校验全局配置; 返回原 dict (不改结构)。

    非法类型/端口越界 → 抛 ConfigValidationError; control 启用但无认证 → CRITICAL 告警。
    """
    try:
        model = ISACConfig.model_validate(config)
    except ValidationError as exc:
        # 只暴露字段级摘要, 不泄露完整堆栈; 消息足够定位错误键。
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigValidationError(f"配置校验失败: {details}") from exc

    control = model.control
    # T3-backend: setup_enabled=true 时首登强制设密码 (admin 端点 428 直到 setup),
    # 视为已有认证保护, 不再 CRITICAL; 仅"启用 control 但既无凭证又无 setup"才告警。
    if control.enabled and not control.api_token and not control.tokens and not control.setup_enabled:
        logger.critical(
            "控制面已启用但未配置认证 (api_token 与 tokens[] 均为空) — 所有 Admin API "
            "(Agent 管理/配置编辑/记忆治理/插件加载) 将无认证暴露。生产部署必须配置 "
            "control.api_token 或 control.tokens[]; 仅本机开发调试可忽略本告警。",
            control_host=control.host,
            control_port=control.port,
        )
    return config


# T1: 占位符 api_key 检测。config.sample.jsonc 的 llm.api_key 默认值 "sk-your-key"
# 此前被 register_llm_provider 当作有效 key (只检查非空), 真实调用 OpenAI 接口
# 永远 401, 用户看到"发消息收不到回复"且日志无明显错误。这些子串覆盖 sample 里的
# 占位形态 ("sk-your-key" / "your-internal-key") 与常见占位习惯 ("changeme" / "xxx"
# / "replace_me" / "example")。命中即视为未配置 → 走 StubProvider + 引导去配。
_PLACEHOLDER_KEY_MARKERS: tuple[str, ...] = (
    "sk-your",
    "your-key",
    "your-internal-key",
    "changeme",
    "replace",
    "example",
    "placeholder",
    "xxx",
    "todo",
    "fill-in",
    "fillme",
)


def is_placeholder_key(api_key: str | None) -> bool:
    """判断 api_key 是否为占位符 (非真实 key)。

    空/None → True (未配置); 命中占位子串 → True; 否则 False。
    小写匹配, 避免 "sk-Your-Key" 漏判。

    不用长度阈值: 测试用 key 如 "sk-test" (7 字符) 不含占位子串, 应视为真实 key;
    真实 key 短于 8 字符极罕见但并非不可, 长度阈值会误伤。
    """
    if not api_key:
        return True
    lowered = api_key.strip().lower()
    return any(marker in lowered for marker in _PLACEHOLDER_KEY_MARKERS)
