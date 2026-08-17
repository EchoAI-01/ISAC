"""U8 SessionWriteGate 专项测试 (预约表 + hold 窗口 + fail-closed + AST 审计)。

验收覆盖 (DEVELOPMENT_PLAN §四 U8):
- 先预约后写入 / 单写者仲裁 / hold 窗口超时作废 (fail-closed);
- 审计测试当场捕获门之外的会话写入路径 (AST 常驻检查);
- catalog drift 检测生效 (工具面/配置键面与入库 catalog 一致)。
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

from isac.runtime.write_gate import SessionWriteGate

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class _Clock:
    """可控 monotonic 时钟 (测试 hold 窗口)。"""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _gate(clock: _Clock | None = None, hold: float = 30.0) -> SessionWriteGate:
    return SessionWriteGate(default_hold_seconds=hold, _now_fn=clock)


# ── 预约/提交/取消语义 ───────────────────────────────────────


def test_reserve_commit_lifecycle() -> None:
    gate = _gate()
    reservation = gate.reserve("s1", "proactive")
    assert reservation is not None
    assert gate.active("s1") is reservation
    assert gate.commit(reservation) is True
    assert gate.active("s1") is None and len(gate) == 0


def test_single_writer_arbitration() -> None:
    gate = _gate()
    first = gate.reserve("s1", "proactive")
    second = gate.reserve("s1", "handoff")
    assert first is not None and second is None  # 先到者得, 后来者放弃
    # 不同会话互不影响
    assert gate.reserve("s2", "handoff") is not None


def test_reservation_frees_after_commit_or_cancel() -> None:
    gate = _gate()
    r1 = gate.reserve("s1", "proactive")
    assert r1 is not None
    gate.commit(r1)
    assert gate.reserve("s1", "handoff") is not None  # 提交后可再预约

    gate2 = _gate()
    r2 = gate2.reserve("s1", "proactive")
    assert r2 is not None
    gate2.cancel(r2)
    assert gate2.reserve("s1", "handoff") is not None  # 取消后可再预约


def test_unregistered_source_rejected() -> None:
    gate = _gate()
    assert gate.reserve("s1", "rogue_writer") is None  # 未登记来源 fail-closed


def test_hold_window_expiry_fail_closed() -> None:
    clock = _Clock()
    gate = _gate(clock, hold=30.0)
    reservation = gate.reserve("s1", "proactive")
    assert reservation is not None

    clock.advance(29.9)
    assert gate.commit(reservation) is True  # 窗口内提交有效

    r2 = gate.reserve("s1", "proactive")
    assert r2 is not None
    clock.advance(30.1)
    assert gate.commit(r2) is False  # 超时作废 fail-closed
    assert gate.active("s1") is None  # 过期租约回收


def test_expired_reservation_allows_new_reserve() -> None:
    clock = _Clock()
    gate = _gate(clock, hold=10.0)
    assert gate.reserve("s1", "proactive") is not None
    clock.advance(11.0)
    # 过期租约惰性回收, 新写者可预约
    assert gate.reserve("s1", "handoff") is not None


def test_commit_wrong_reservation_rejected() -> None:
    gate = _gate()
    r1 = gate.reserve("s1", "proactive")
    assert r1 is not None
    gate.cancel(r1)
    assert gate.commit(r1) is False  # 已取消的租约不能提交
    # 过期后被新写者接手: 旧租约提交失败 (防互踩)
    clock = _Clock()
    gate2 = _gate(clock, hold=5.0)
    old = gate2.reserve("s1", "proactive")
    assert old is not None
    clock.advance(6.0)
    new = gate2.reserve("s1", "handoff")
    assert new is not None
    assert gate2.commit(old) is False
    assert gate2.commit(new) is True


def test_hold_seconds_clamped() -> None:
    gate = _gate()
    tiny = gate.reserve("s1", "proactive", hold_seconds=0.001)
    huge = gate.reserve("s2", "proactive", hold_seconds=99999.0)
    assert tiny is not None and tiny.hold_seconds >= 1.0
    assert huge is not None and huge.hold_seconds <= 600.0


# ── AST 审计: 门之外的会话写入路径当场捕获 ──────────────────

# 允许直接触碰会话状态机的文件 (门内/状态机本体):
# - manager.py: 强制话轮经 SessionWriteGate 预约后写入 (门内写者)
# - conversation/runtime.py + scheduler.py: 状态机与等待调度本体
# 其余文件出现 forced_turn 赋值或 transition_to 调用 = 绕过仲裁门。
_AUDIT_ALLOWLIST = {
    "isac/runtime/manager.py",
    "isac/runtime/conversation/runtime.py",
    "isac/runtime/conversation/scheduler.py",
}


def _iter_python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_ast_audit_no_session_write_outside_gate() -> None:
    """审计测试: isac/ 内门之外的 forced_turn 赋值 / transition_to 调用即失败。

    故意绕过 SessionWriteGate 直接写会话状态机的代码会被本测试当场捕获
    (U8 验收: 审计测试能当场捕获故意绕过的写入)。
    """
    violations: list[str] = []
    for path in _iter_python_files(REPO_ROOT / "isac"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _AUDIT_ALLOWLIST:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # forced_turn 属性赋值 (runtime.forced_turn = ...)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "forced_turn":
                        violations.append(f"{rel}:{node.lineno} forced_turn 赋值")
            # transition_to(...) 调用
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "transition_to":
                    violations.append(f"{rel}:{node.lineno} transition_to 调用")
    assert violations == [], (
        "发现 SessionWriteGate 之外的会话状态机写入点 (绕过仲裁门):\n" + "\n".join(violations)
    )


def test_write_gate_is_wired_in_main_services() -> None:
    """门必须接线进生产 services 袋 (防"定义了未接线")。U2 后装配在 bootstrap.py。"""
    bootstrap_src = (REPO_ROOT / "isac" / "bootstrap.py").read_text(encoding="utf-8")
    assert "session_write_gate" in bootstrap_src
    assert "SessionWriteGate()" in bootstrap_src


# ── 治理门禁: catalog 一致性 (与 CI --check 同语义) ──────────


def _load_script(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tool_catalog_no_drift() -> None:
    gen = _load_script("gen_tool_catalog", REPO_ROOT / "scripts" / "gen_tool_catalog.py")
    catalog = gen.build_catalog()
    committed = json.loads((REPO_ROOT / "data" / "catalogs" / "tools.json").read_text(encoding="utf-8"))
    assert committed == catalog, "工具 catalog 漂移: 重新运行 scripts/gen_tool_catalog.py"
    assert catalog["tool_count"] >= 25  # 规模哨兵: 工具面不应骤减


def test_config_catalog_no_drift() -> None:
    gen = _load_script("gen_config_catalog", REPO_ROOT / "scripts" / "gen_config_catalog.py")
    sample = gen._load_sample(REPO_ROOT / "data" / "config.sample.jsonc")  # noqa: SLF001
    catalog = gen.build_catalog(sample)
    committed = json.loads((REPO_ROOT / "data" / "catalogs" / "config_keys.json").read_text(encoding="utf-8"))
    assert committed == catalog, "配置 catalog 漂移: 重新运行 scripts/gen_config_catalog.py"
    assert catalog["top_level_count"] >= 15
