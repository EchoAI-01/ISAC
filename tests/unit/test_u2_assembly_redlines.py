"""U2 装配层重构红线测试 (常驻 CI)。

验收 (DEVELOPMENT_PLAN §四 U2):
- main.py 薄入口 (行数冻结只减不增);
- bootstrap/dispatch/wiring/cli 各 ≤500 行;
- ServiceContainer 核心键类型化 (键错配在类型层不可能);
- 单向导入链保持 (拆分模块不反向依赖 main)。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 红线: 行数上限 (只减不增 —— 放宽上限即架构债回潮)
_LIMITS: dict[str, int] = {
    "isac/main.py": 120,
    "isac/dispatch.py": 500,
    "isac/wiring.py": 500,
    "isac/bootstrap.py": 500,
    "isac/control/bootstrap.py": 500,
    "isac/runtime/plugin_bootstrap.py": 500,
}


def test_module_line_limits() -> None:
    for rel, limit in _LIMITS.items():
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} 不存在 (U2 拆分结构被破坏)"
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= limit, f"{rel} 行数 {lines} 超红线 {limit} (只减不增)"


def test_main_is_thin_reexport_entry() -> None:
    """main.py 不得再定义业务函数 —— 只保留 re-export 兼容面。"""
    tree = ast.parse((REPO_ROOT / "isac" / "main.py").read_text(encoding="utf-8"))
    funcs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert funcs == [], f"main.py 应无函数定义 (薄入口), 发现: {funcs}"


def test_service_container_core_keys_typed() -> None:
    """ServiceContainer 核心键为类型化属性 (键错配在类型层不可能)。"""
    from isac.runtime.services import ServiceContainer

    core_keys = {
        "global_config", "metrics", "provider_manager", "model_catalog",
        "model_router", "artifact_store", "uploads_store", "usage_recorder",
        "session_event_store", "media_normalizer", "channel_registry",
        "session_mgr", "session_lock", "session_write_gate",
    }
    for key in core_keys:
        assert isinstance(getattr(ServiceContainer, key), property), f"核心键 {key} 缺类型化属性"

    # dict 语义保持: 既有 services["x"] / get / 解包调用方零改动
    container = ServiceContainer({"global_config": {"a": 1}})
    assert container.global_config == {"a": 1}
    assert container["global_config"] == {"a": 1}
    assert container.get("missing") is None
    assert {**container, "extra": 2}["extra"] == 2
    assert isinstance(container, dict)


def test_split_modules_do_not_import_main() -> None:
    """单向依赖: 拆分模块不得反向 import isac.main (防薄入口环依赖)。"""
    targets = [
        "isac/dispatch.py", "isac/wiring.py", "isac/bootstrap.py",
        "isac/control/bootstrap.py", "isac/runtime/plugin_bootstrap.py",
        "isac/channel/registration.py", "isac/runtime/mesh/query.py",
    ]
    for rel in targets:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "isac.main" and not str(node.module or "").startswith("isac.main."), (
                    f"{rel} 反向导入 isac.main (破坏单向链)"
                )
