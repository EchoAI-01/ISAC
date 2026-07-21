"""数据备份/导出/导入脚本 (DEVELOPMENT_PLAN.md Day 85)。

用法: uv run python scripts/export.py --out backup.zip
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="ISAC 数据导出工具")
    parser.add_argument("--out", default="backup.zip", help="导出文件")
    parser.add_argument("--src", default="data/", help="数据目录")
    args = parser.parse_args()
    raise NotImplementedError(f"TODO(Day 85): 实现数据导出 ({args.src} → {args.out})")


if __name__ == "__main__":
    main()
