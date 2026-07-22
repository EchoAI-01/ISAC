"""数据备份/导出/导入脚本。

用法: uv run python scripts/export.py --out backup.zip
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="ISAC 数据导出工具")
    parser.add_argument("--out", default="backup.zip", help="导出文件")
    parser.add_argument("--src", default="data/", help="数据目录")
    args = parser.parse_args()
    raise NotImplementedError(f"scripts.export: 数据导出尚未实现 ({args.src} → {args.out})")


if __name__ == "__main__":
    main()
