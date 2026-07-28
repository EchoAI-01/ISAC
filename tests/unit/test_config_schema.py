"""配置 schema 校验单测 (X2/R4: 空 api_token 静默禁用认证 + 非法配置)。

验证 validate_config: 合法配置原样返回且保留未知节; 非法 port/类型抛
ConfigValidationError; control 启用但无认证时 CRITICAL 告警 (不抛); 各安全组合
(有 api_token / 有 tokens[] / 未启用) 不误报。

告警断言用 monkeypatch 把模块级 logger 替换为记录器直接断言 logger.critical 调用:
本项目 logger 走 structlog PrintLoggerFactory, 导入期即冻结 stderr 引用, capsys/
capfd 均抓不到; 直接探针 logger 调用最确定, 也正是被测行为本身。
"""

from __future__ import annotations

from typing import Any

import pytest

from isac.utils import config_schema
from isac.utils.config_schema import ConfigValidationError, validate_config


class _RecordingLogger:
    """只记录 critical 调用的探针 logger (validate_config 仅用到 .critical)。"""

    def __init__(self) -> None:
        self.critical_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def critical(self, *args: Any, **kwargs: Any) -> None:
        self.critical_calls.append((args, kwargs))


@pytest.fixture
def rec_logger(monkeypatch: pytest.MonkeyPatch) -> _RecordingLogger:
    rec = _RecordingLogger()
    monkeypatch.setattr(config_schema, "logger", rec)
    return rec


def test_valid_config_passthrough_preserves_unknown_sections() -> None:
    cfg = {
        "debug": True,
        "control": {"enabled": True, "port": 8091, "api_token": "secret"},
        "llm": {"provider": "openai", "model": "gpt-4o"},  # 未建模节应原样保留
        "channels": {"onebot": {"enabled": True, "port": 8080}},
    }
    out = validate_config(cfg)
    assert out is cfg  # 返回原对象, 不改结构
    assert out["llm"]["model"] == "gpt-4o"
    assert out["channels"]["onebot"]["port"] == 8080


def test_invalid_port_out_of_range_raises() -> None:
    with pytest.raises(ConfigValidationError, match="port"):
        validate_config({"control": {"port": 99999}})


def test_invalid_port_type_raises() -> None:
    with pytest.raises(ConfigValidationError, match="port"):
        validate_config({"control": {"port": "not-a-number"}})


def test_missing_control_section_ok() -> None:
    out = validate_config({"debug": False})
    assert out == {"debug": False}


def test_control_enabled_without_auth_logs_critical(rec_logger: _RecordingLogger) -> None:
    validate_config({"control": {"enabled": True, "api_token": "", "tokens": []}})
    assert rec_logger.critical_calls  # 无认证 → 必须高声告警


def test_control_enabled_with_api_token_no_warning(rec_logger: _RecordingLogger) -> None:
    validate_config({"control": {"enabled": True, "api_token": "tok"}})
    assert not rec_logger.critical_calls


def test_control_enabled_with_tokens_no_warning(rec_logger: _RecordingLogger) -> None:
    validate_config(
        {"control": {"enabled": True, "api_token": "", "tokens": [{"token": "t", "scopes": ["*"]}]}}
    )
    assert not rec_logger.critical_calls


def test_control_disabled_without_auth_no_warning(rec_logger: _RecordingLogger) -> None:
    validate_config({"control": {"enabled": False, "api_token": ""}})
    assert not rec_logger.critical_calls


def test_sample_config_passes_validation() -> None:
    """开箱示例配置必须通过校验 (control 默认关闭, 无 CRITICAL)。"""
    from isac.utils.config import load_config

    cfg = load_config("data/config.sample.jsonc")
    assert cfg["control"]["enabled"] is False


# ── Fix-30: control.* 显式 null 等价于未配置, 不应崩溃启动 ──────────


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tokens", None),
        ("api_token", None),
        ("host", None),
        ("enabled", None),
        ("port", None),
    ],
)
def test_control_field_explicit_null_falls_back_to_default(field: str, value: None) -> None:
    """此前这些字段类型不接受 None, 手工维护的 JSONC 写 "字段": null 很常见,
    历史行为 (schema 校验之前) 对这些字段一律按 falsy=未配置处理, 完全无害;
    加了 schema 后应该维持这个宽容度, 不应抛 ConfigValidationError 崩溃。"""
    out = validate_config({"control": {field: value}})
    assert out == {"control": {field: value}}  # 返回原 dict 不变, 只是不崩溃


def test_top_level_control_explicit_null_falls_back_to_default() -> None:
    """顶层 "control": null (整节都没配置) 同样应该等价于未配置, 不崩溃。"""
    out = validate_config({"control": None})
    assert out == {"control": None}


def test_control_null_fields_do_not_suppress_missing_auth_warning(
    rec_logger: _RecordingLogger,
) -> None:
    """null 落回默认值后, "enabled=true 但无认证" 的 CRITICAL 告警逻辑应正常
    生效 (证明 null 真的被当成默认值参与后续判断, 不是被忽略校验)。"""
    validate_config({"control": {"enabled": True, "api_token": None, "tokens": None}})
    assert rec_logger.critical_calls


def test_invalid_port_type_still_raises_after_null_handling() -> None:
    """回归防护: null 特例处理不能放宽对真正非法值 (类型错/越界) 的校验——
    只有字面 None 才走默认值分支, 其余非法输入仍应正常抛错。"""
    with pytest.raises(ConfigValidationError, match="port"):
        validate_config({"control": {"port": "not-a-number"}})
    with pytest.raises(ConfigValidationError, match="port"):
        validate_config({"control": {"port": 99999}})
