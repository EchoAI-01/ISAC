#!/usr/bin/env python3
"""U8 治理门禁: 配置键 catalog 生成 + 漂移检测。

解析 data/config.sample.jsonc 顶层与二级配置键, 归一化为
data/catalogs/config_keys.json —— 配置面变更 (增删键) 未重新生成 catalog 时
CI --check 失败, 强制配置演进留档 (治理门禁, U8)。

用法:
    python scripts/gen_config_catalog.py           # 重新生成
    python scripts/gen_config_catalog.py --check   # CI 漂移检测 (不一致 exit=1)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PATH = REPO_ROOT / "data" / "config.sample.jsonc"
OUT_PATH = REPO_ROOT / "data" / "catalogs" / "config_keys.json"


def _load_sample(path: Path) -> dict[str, Any]:
    try:
        import json5

        return json5.loads(path.read_text(encoding="utf-8"))
    except ImportError:
        # 无 json5 时退化为去注释解析 (sample 注释均为 // 行)
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("//")]
        return json.loads("\n".join(lines))


def build_catalog(sample: dict[str, Any]) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    for key, value in sorted(sample.items()):
        if isinstance(value, dict):
            keys[key] = {"children": sorted(value.keys())}
        elif isinstance(value, list):
            keys[key] = {"children": []}
        else:
            keys[key] = {"children": []}
    return {
        "schema_version": 1,
        "top_level_count": len(keys),
        "source": "data/config.sample.jsonc",
        "keys": keys,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="配置键 catalog 生成/漂移检测")
    parser.add_argument("--check", action="store_true", help="只比对不写入, 漂移 exit=1")
    parser.add_argument("--sample", default=str(SAMPLE_PATH))
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    sample = _load_sample(Path(args.sample))
    catalog = build_catalog(sample)
    out_path = Path(args.out)

    if args.check:
        if not out_path.is_file():
            print(f"[fail] catalog 不存在: {out_path} (先运行不带 --check 生成)", file=sys.stderr)
            return 1
        committed = json.loads(out_path.read_text(encoding="utf-8"))
        if committed != catalog:
            print(
                "[fail] 配置 catalog 漂移: config.sample.jsonc 键面已变更, "
                "重新运行 scripts/gen_config_catalog.py",
                file=sys.stderr,
            )
            return 1
        print(f"[ok] 配置 catalog 一致 ({catalog['top_level_count']} 顶层键)")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] 配置 catalog 已生成: {catalog['top_level_count']} 顶层键 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
