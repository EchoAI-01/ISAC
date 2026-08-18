#!/usr/bin/env python3
"""U8 治理门禁: 工具 catalog 生成 + 漂移检测。

从 isac/agent/tools/ 自动发现全部 Tool 子类 (可无参构造者取 name/description),
合并 ToolPermission.DEFAULT_POLICY 默认策略, 归一化为 data/catalogs/tools.json。

用法:
    python scripts/gen_tool_catalog.py           # 重新生成
    python scripts/gen_tool_catalog.py --check   # CI 漂移检测 (不一致 exit=1)

漂移语义: 新增/改名/删除工具或默认策略变化后未重新生成 catalog → --check 失败,
强制把"工具面变更"留在版本库记录里 (治理门禁, U8)。
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pkgutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

OUT_PATH = REPO_ROOT / "data" / "catalogs" / "tools.json"


def discover_tools() -> dict[str, dict[str, str]]:
    """遍历 isac.agent.tools 全部模块, 收集可无参实例化的 Tool 子类。"""
    import isac.agent.tools as tools_pkg
    from isac.agent.tools.base import Tool

    found: dict[str, dict[str, str]] = {}
    for module_info in pkgutil.walk_packages(tools_pkg.__path__, prefix="isac.agent.tools."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # noqa: BLE001 可选依赖缺失模块跳过
            print(f"[warn] 模块导入失败, 跳过: {module_info.name} ({exc})", file=sys.stderr)
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if not issubclass(obj, Tool) or obj is Tool or inspect.isabstract(obj):
                continue
            if obj.__module__ != module_info.name:
                continue  # re-export 去重
            try:
                instance = obj()
                tool_name = str(instance.name)
                description = str(instance.description)
            except Exception:  # noqa: BLE001 需参构造的工具只登记存在性
                continue
            found[tool_name] = {"module": module_info.name, "description": description}
    return found


def build_catalog() -> dict[str, object]:
    from isac.agent.tools.base import ToolPermission

    tools = discover_tools()
    default_policy = dict(ToolPermission.DEFAULT_POLICY)
    entries = {
        name: {
            "module": info["module"],
            "description": info["description"],
            "default_policy": default_policy.get(name, "allow"),
        }
        for name, info in sorted(tools.items())
    }
    return {
        "schema_version": 1,
        "tool_count": len(entries),
        "tools": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="工具 catalog 生成/漂移检测")
    parser.add_argument("--check", action="store_true", help="只比对不写入, 漂移 exit=1")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    catalog = build_catalog()
    rendered = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    out_path = Path(args.out)

    if args.check:
        if not out_path.is_file():
            print(f"[fail] catalog 不存在: {out_path} (先运行不带 --check 生成)", file=sys.stderr)
            return 1
        committed = out_path.read_text(encoding="utf-8")
        if json.loads(committed) != catalog:
            print("[fail] 工具 catalog 漂移: 工具面已变更, 重新运行 scripts/gen_tool_catalog.py", file=sys.stderr)
            return 1
        print(f"[ok] 工具 catalog 一致 ({catalog['tool_count']} 工具)")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"[ok] 工具 catalog 已生成: {catalog['tool_count']} 工具 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
