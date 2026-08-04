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
    "enabled": False,
    "host": "127.0.0.1",
    "port": 8765,
    "api_token": "",
    "tokens": [],
}


class ControlConfig(BaseModel):
    """控制面配置的受校验字段 (extra="allow" 放行 workflow/plugins/agents_dir 等其余键)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    api_token: str = ""
    tokens: list[Any] = Field(default_factory=list)

    @field_validator("enabled", "host", "port", "api_token", "tokens", mode="before")
    @classmethod
    def _none_means_unset(cls, v: Any, info: ValidationInfo) -> Any:
        """显式 null 等价于该字段未配置, 落回默认值; 其余非法值 (类型错/越界)
        原样传给标准校验, 仍按预期抛 ConfigValidationError, 不受本 fix 影响。"""
        if v is None:
            return _CONTROL_FIELD_DEFAULTS[str(info.field_name)]
        return v


class ISACConfig(BaseModel):
    """顶层配置的受校验字段。extra="allow" 让未建模的节 (llm/memory/channels/...) 原样放行。"""

    model_config = ConfigDict(extra="allow")

    debug: bool = False
    log_level: str = "info"
    control: ControlConfig = Field(default_factory=ControlConfig)

    @field_validator("control", mode="before")
    @classmethod
    def _none_control_means_unset(cls, v: Any) -> Any:
        """顶层 "control": null 同样等价于未配置该节 (退化成全默认 ControlConfig),
        而不是把 None 当 ControlConfig 实例校验失败崩溃。"""
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
    if control.enabled and not control.api_token and not control.tokens:
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
