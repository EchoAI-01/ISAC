"""数据迁移脚本 (DEVELOPMENT_PLAN.md Day 85: AstrBot / MaiBot → ISAC)。

用法: uv run python scripts/migrate.py --from astrbot --src <path> --dst data/
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="ISAC 数据迁移工具")
    parser.add_argument("--from", dest="source", choices=["astrbot", "maibot"], required=True)
    parser.add_argument("--src", required=True, help="源数据目录")
    parser.add_argument("--dst", default="data/", help="目标数据目录")
    args = parser.parse_args()
    raise NotImplementedError(f"TODO(Day 85): 实现 {args.source} → ISAC 数据迁移 ({args.src} → {args.dst})")


if __name__ == "__main__":
    main()
