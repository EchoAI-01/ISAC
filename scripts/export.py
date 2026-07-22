"""数据备份/导出/导入脚本。

支持:
- export: 把 data/ 目录打包为 zip 备份 (排除 audit.ndjson 等运行时日志可选)
- import: 从 zip 恢复到 data/ 目录

用法:
    uv run python scripts/export.py export --out backup.zip [--src data/] [--include-logs]
    uv run python scripts/export.py import --in backup.zip [--dst data/]
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 默认排除的运行时日志 (可由 --include-logs 覆盖)
DEFAULT_EXCLUDES = {"audit.ndjson", "memory/metadata.db-wal", "memory/metadata.db-shm"}


def main() -> None:
    parser = argparse.ArgumentParser(description="ISAC 数据导出/导入工具")
    sub = parser.add_subparsers(dest="command", required=True)

    export_p = sub.add_parser("export", help="导出 data/ 到 zip")
    export_p.add_argument("--out", default="backup.zip", help="导出文件路径")
    export_p.add_argument("--src", default="data/", help="源数据目录")
    export_p.add_argument(
        "--include-logs", action="store_true", help="包含运行时日志 (默认排除 audit.ndjson)"
    )

    import_p = sub.add_parser("import", help="从 zip 恢复到 data/")
    import_p.add_argument("--in", dest="input", required=True, help="zip 文件路径")
    import_p.add_argument("--dst", default="data/", help="目标数据目录")
    import_p.add_argument(
        "--overwrite", action="store_true", help="覆盖已存在文件 (默认 skip)"
    )

    args = parser.parse_args()

    if args.command == "export":
        report = export_data(
            Path(args.src), Path(args.out), include_logs=args.include_logs
        )
    elif args.command == "import":
        report = import_data(
            Path(args.input), Path(args.dst), overwrite=args.overwrite
        )
    else:  # pragma: no cover
        raise SystemExit(f"未知命令: {args.command}")

    print(json.dumps(report, ensure_ascii=False, indent=2))


def export_data(src: Path, out: Path, *, include_logs: bool = False) -> dict[str, Any]:
    """打包 src 目录为 zip。"""
    if not src.exists():
        raise SystemExit(f"源目录不存在: {src}")
    src = src.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    excludes = set() if include_logs else DEFAULT_EXCLUDES
    file_count = 0
    total_size = 0

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in src.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(src).as_posix()
            if rel in excludes:
                continue
            # 排除 .venv 与 __pycache__
            if ".venv" in path.parts or "__pycache__" in path.parts:
                continue
            zf.write(path, arcname=rel)
            file_count += 1
            total_size += path.stat().st_size

    logger.info(
        "导出完成",
        out=str(out),
        files=file_count,
        total_size_mb=round(total_size / 1024 / 1024, 2),
    )
    return {
        "ok": True,
        "out": str(out),
        "files": file_count,
        "total_size_bytes": total_size,
        "include_logs": include_logs,
    }


def import_data(zip_path: Path, dst: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """从 zip 恢复到 dst 目录。"""
    if not zip_path.exists():
        raise SystemExit(f"zip 文件不存在: {zip_path}")
    dst.mkdir(parents=True, exist_ok=True)

    file_count = 0
    skipped = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = dst / info.filename
            if target.exists() and not overwrite:
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src_fp, target.open("wb") as dst_fp:
                shutil.copyfileobj(src_fp, dst_fp)
            file_count += 1

    logger.info(
        "导入完成",
        dst=str(dst),
        files=file_count,
        skipped=skipped,
        overwrite=overwrite,
    )
    return {
        "ok": True,
        "dst": str(dst),
        "files": file_count,
        "skipped": skipped,
        "overwrite": overwrite,
    }


if __name__ == "__main__":
    main()
