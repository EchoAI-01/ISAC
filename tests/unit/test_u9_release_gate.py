"""U9 发布门禁常驻测试: "定义了未接线"清零审计 + 红线指标。

验收 (DEVELOPMENT_PLAN §四 U9):
- "零引用安全常量" lint 全仓通过 —— 历史发现的未接线符号登记成册 (UNWIRED_LEDGER),
  审计断言每个符号在 isac/ 内有定义之外的真实引用; 新发现未接线项先修再删条目。
- 红线指标 (main.py 行数 / services 键数 / 硬编码门控词条目数 / 迁移棘轮) 只减不增,
  与 scripts/check_redlines.py --check (CI catalog-drift job 内) 同逻辑。
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 未接线登记册: (符号, 定义文件)。历史上 isac-deep Review 发现的"定义了未接线"
# 安全常量/机制, 接线清偿后在此登记并常驻审计 —— 引用数掉回 1 (仅定义) 即失败。
UNWIRED_LEDGER: tuple[tuple[str, str], ...] = (
    ("MAX_EXTRACTED_BYTES", "isac/plugin/installer.py"),  # Fix-86 解压体积上限
    ("record_health", "isac/provider/router.py"),  # U7 可达性上报接线
    ("_ALLOWED_SOURCES", "isac/runtime/write_gate.py"),  # U8 门内写者名单
    ("DEFAULT_HOLD_SECONDS", "isac/runtime/write_gate.py"),  # U8 hold 窗口默认
    ("VALID_STRATEGIES", "isac/gating/profile.py"),  # U3 策略档位归一
    ("GATING_MARKER_KINDS", "isac/locales/__init__.py"),  # U3 词表规范键
    ("SNAPSHOT_SCHEMA_VERSION", "isac/provider/capabilities.py"),  # U7 快照 schema
)


def _load_redlines() -> object:
    spec = importlib.util.spec_from_file_location(
        "check_redlines", REPO_ROOT / "scripts" / "check_redlines.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unwired_ledger_all_symbols_referenced() -> None:
    """登记册内每个符号必须有真实使用点 (防回退成死代码)。

    接线判定: 定义文件之外有引用, 或定义文件内除定义语句外另有引用
    (模块内部消费也算接线 —— "未接线"指零使用的死定义)。
    """
    failures: list[str] = []
    for symbol, definition_file in UNWIRED_LEDGER:
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")
        external = False
        internal_uses = 0
        for path in (REPO_ROOT / "isac").rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            hits = pattern.findall(path.read_text(encoding="utf-8"))
            if rel == definition_file:
                internal_uses = max(internal_uses, len(hits) - 1)  # 减去定义行本身
            elif hits:
                external = True
        if not external and internal_uses <= 0:
            failures.append(f"{symbol} (定义于 {definition_file}) 无任何使用点 —— 定义了未接线")
    assert failures == [], "发现未接线符号:\n" + "\n".join(failures)


def test_redlines_all_green() -> None:
    """红线指标只减不增 (与 CI scripts/check_redlines.py 同逻辑)。"""
    redlines = _load_redlines()
    violations = redlines.check()
    assert violations == [], "红线越界:\n" + "\n".join(violations)


def test_no_placeholder_or_todo_security_paths() -> None:
    """安全相关模块不得留 TODO/FIXME 占位 (发布门禁卫生检查)。"""
    security_paths = [
        "isac/runtime/write_gate.py",
        "isac/agent/tools/guard.py",
        "isac/agent/tools/approval.py",
        "isac/agent/tools/decision_reasons.py",
        "isac/utils/security.py",
    ]
    offenders: list[str] = []
    for rel in security_paths:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "TODO" in line or "FIXME" in line:
                offenders.append(f"{rel}:{i} {line.strip()[:80]}")
    assert offenders == [], "安全模块存在占位标记:\n" + "\n".join(offenders)
