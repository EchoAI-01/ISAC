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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigValidationError(ValueError):
    """配置校验失败 (非法端口/类型等)。启动期抛出, 消息指明失败字段。"""


class ControlConfig(BaseModel):
    """控制面配置的受校验字段 (extra="allow" 放行 workflow/plugins/agents_dir 等其余键)。"""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    api_token: str = ""
    tokens: list[Any] = Field(default_factory=list)


class ISACConfig(BaseModel):
    """顶层配置的受校验字段。extra="allow" 让未建模的节 (llm/memory/channels/...) 原样放行。"""

    model_config = ConfigDict(extra="allow")

    debug: bool = False
    log_level: str = "info"
    control: ControlConfig = Field(default_factory=ControlConfig)


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
