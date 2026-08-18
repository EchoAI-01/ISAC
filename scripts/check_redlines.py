#!/usr/bin/env python3
"""U9 红线指标检查 (GA 门槛, 只减不增)。

红线 (DEVELOPMENT_PLAN §三之五 工程纪律第 3 条 + U9 验收):
- main.py 行数 ≤ 120 (U2 薄入口, 回潮即失败);
- dispatch/wiring/bootstrap 各 ≤ 500 行;
- services 袋键数 ≤ 36 (build_services 字面量 + bootstrap 注册并集);
- constants.py 硬编码门控词条目数 ≤ 27 (U3 已迁 locales, 只减不增);
- 残余 services 字符串键访问数 ≤ 167 (ServiceContainer 迁移棘轮; U9 冻结 205,
  N5/Z1-A 收紧至 167)。

用法:
    python scripts/check_redlines.py           # 检查, 越线 exit=1
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 红线基线 (2026-08-18 U9 冻结): 放宽即架构债回潮, 只允许收紧。
MAIN_MAX_LINES = 120
MODULE_MAX_LINES = 500
SERVICES_KEYS_MAX = 36
GATING_MARKERS_MAX = 27
SERVICES_GET_REMAINING_MAX = 130

_LINE_LIMITS = {
    "isac/main.py": MAIN_MAX_LINES,
    "isac/dispatch.py": MODULE_MAX_LINES,
    "isac/wiring.py": MODULE_MAX_LINES,
    "isac/bootstrap.py": MODULE_MAX_LINES,
}


def line_count(rel: str) -> int:
    return len((REPO_ROOT / rel).read_text(encoding="utf-8").splitlines())


def services_key_count() -> int:
    """build_services 字面量键 + bootstrap services["x"]= 注册键的并集大小。"""
    keys: set[str] = set()
    wiring = ast.parse((REPO_ROOT / "isac" / "wiring.py").read_text(encoding="utf-8"))
    for node in ast.walk(wiring):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ServiceContainer" and node.args:
            dict_node = node.args[0]
            if isinstance(dict_node, ast.Dict):
                keys.update(k.value for k in dict_node.keys if isinstance(k, ast.Constant))
    bootstrap = ast.parse((REPO_ROOT / "isac" / "bootstrap.py").read_text(encoding="utf-8"))
    for node in ast.walk(bootstrap):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "services"
                    and isinstance(tgt.slice, ast.Constant)
                ):
                    keys.add(tgt.slice.value)
    return len(keys)


def gating_marker_entry_count() -> int:
    """constants.py 三组硬编码门控词表条目总数 (U3 后只减不增)。"""
    tree = ast.parse((REPO_ROOT / "isac" / "core" / "constants.py").read_text(encoding="utf-8"))
    total = 0
    targets = {"GATING_QUESTION_MARKERS", "GATING_REQUEST_MARKERS", "GATING_CONSULT_MARKERS"}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in targets and isinstance(node.value, ast.Tuple):
                total += len(node.value.elts)
    return total


def services_get_remaining() -> int:
    """isac/ 内残余 services 字符串键访问数 (get/索引), ServiceContainer 迁移棘轮。"""
    count = 0
    for path in (REPO_ROOT / "isac").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        count += text.count("services.get(") + text.count('services["')
    return count


def check() -> list[str]:
    """返回越线项列表 (空 = 全绿)。"""
    violations: list[str] = []
    for rel, limit in _LINE_LIMITS.items():
        n = line_count(rel)
        if n > limit:
            violations.append(f"{rel}: {n} 行 > 红线 {limit}")
    n = services_key_count()
    if n > SERVICES_KEYS_MAX:
        violations.append(f"services 袋键数 {n} > 红线 {SERVICES_KEYS_MAX}")
    n = gating_marker_entry_count()
    if n > GATING_MARKERS_MAX:
        violations.append(f"硬编码门控词条目数 {n} > 红线 {GATING_MARKERS_MAX}")
    n = services_get_remaining()
    if n > SERVICES_GET_REMAINING_MAX:
        violations.append(f"残余 services 字符串键访问 {n} > 红线 {SERVICES_GET_REMAINING_MAX}")
    return violations


def main() -> int:
    violations = check()
    if violations:
        for v in violations:
            print(f"[fail] 红线越界: {v}", file=sys.stderr)
        return 1
    print(
        f"[ok] 红线全绿: main.py {line_count('isac/main.py')} 行, "
        f"services 键 {services_key_count()}, 门控词 {gating_marker_entry_count()} 条, "
        f"残余 services 访问 {services_get_remaining()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
