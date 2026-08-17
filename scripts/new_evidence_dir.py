#!/usr/bin/env python3
"""U8 evidence 目录规范化: 创建 evidence/YYYY-MM-DD-<slug>/ 留档目录。

约定 (DEVELOPMENT_PLAN §四 U8): 真机证据**必留档** —— 每次真机验收/冒烟的
证据 (日志、截图、脚本输出) 存入 ``evidence/<日期>-<slug>/``, 目录内附
README.md 记录验收项与结论。日期自动取当天, slug 必填。

用法:
    python scripts/new_evidence_dir.py u8-snapshot-replay
    → evidence/2026-08-18-u8-snapshot-replay/ (含 README.md 骨架)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = REPO_ROOT / "evidence"

README_TEMPLATE = """# {slug}

- **日期**: {date}
- **验收项**: (DEVELOPMENT_PLAN 对应条目)
- **结论**: PASS / FAIL

## 证据清单

- (日志/截图/脚本输出逐项列出)

## 复现方式

```
(命令或步骤)
```
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 evidence 留档目录 (日期-slug)")
    parser.add_argument("slug", help="留档主题短 slug (小写字母/数字/短横线)")
    args = parser.parse_args()

    slug = args.slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,64}", slug):
        print(f"[fail] slug 非法: {slug!r} (只允许小写字母/数字/短横线, 2-65 位)", file=sys.stderr)
        return 1

    target = EVIDENCE_ROOT / f"{date.today().isoformat()}-{slug}"
    if target.exists():
        print(f"[warn] 目录已存在: {target}")
        return 0
    target.mkdir(parents=True)
    (target / "README.md").write_text(
        README_TEMPLATE.format(slug=slug, date=date.today().isoformat()), encoding="utf-8"
    )
    print(f"[ok] evidence 目录已创建: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
