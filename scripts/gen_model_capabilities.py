#!/usr/bin/env python3
"""U7 模型能力快照生成器: models.dev → data/model_capabilities.json。

用法:
    python scripts/gen_model_capabilities.py            # 在线拉取 models.dev
    python scripts/gen_model_capabilities.py --source x.json  # 离线: 从本地文件归一化
    python scripts/gen_model_capabilities.py --check    # 只校验现有快照新鲜度 (CI 用)

- 数据源 (拍板 #4): models.dev api.json (覆盖 2700+ 模型, 零维护);
  个别国产新模型晚收录时用 ``data/model_capabilities.overrides.json`` 手动补录
  (同键格式 "provider/model", 字段覆盖快照)。
- CI: .github/workflows/model-capabilities.yml 每周跑本脚本并提交差异;
  新鲜度 drift 由 tests/unit/test_u7_model_capabilities.py 报警 (过期即失败)。
- 仅用标准库 (urllib), 不新增依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MODELS_DEV_URL = "https://models.dev/api.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "data" / "model_capabilities.json"
OVERRIDES_PATH = REPO_ROOT / "data" / "model_capabilities.overrides.json"
FETCH_TIMEOUT_SECONDS = 60


def _fetch_models_dev(url: str = MODELS_DEV_URL) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "isac-capability-snapshot/1.0"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def normalize(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """models.dev api.json → {"provider/model": {能力字段}} 归一化。

    models.dev 结构: {<provider>: {"models": {<model>: {"limit": {"context"},
    "tool_call", "vision"/"attachment", "cost": {...}, ...}}}}; 字段缺失容错。
    """
    models: dict[str, dict[str, Any]] = {}
    for provider_id, provider_entry in raw.items():
        if not isinstance(provider_entry, dict):
            continue
        for model_id, model in (provider_entry.get("models") or {}).items():
            if not isinstance(model, dict):
                continue
            limit = model.get("limit") or {}
            modalities_in = {"text"}
            if model.get("vision") or model.get("attachment"):
                modalities_in.add("image")
            if model.get("audio"):
                modalities_in.add("audio")
            cost = model.get("cost") or {}
            entry: dict[str, Any] = {
                "context_window": limit.get("context"),
                "supports_tools": _bool(model.get("tool_call")),
                "supports_vision": _bool(model.get("vision")),
                "modalities_in": sorted(modalities_in),
                "modalities_out": ["text"],
            }
            if isinstance(cost, dict) and cost:
                entry["x_cost"] = cost
            models[f"{provider_id}/{model_id}".lower()] = entry
    return models


def merge_overrides(models: dict[str, dict[str, Any]], overrides_path: Path) -> int:
    """合并手动补录 overrides (同键覆盖/新增), 返回合并条目数。"""
    if not overrides_path.is_file():
        return 0
    try:
        overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] overrides 读取失败, 跳过: {exc}", file=sys.stderr)
        return 0
    count = 0
    for key, entry in overrides.items():
        if not isinstance(entry, dict):
            continue
        key = key.lower()
        models.setdefault(key, {}).update(entry)
        count += 1
    return count


def build_snapshot(source: dict[str, Any], source_name: str, overrides_path: Path) -> dict[str, Any]:
    models = normalize(source)
    merged = merge_overrides(models, overrides_path)
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": source_name,
        "model_count": len(models),
        "override_count": merged,
        "models": dict(sorted(models.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="生成模型能力快照 (models.dev → JSON)")
    parser.add_argument("--source", help="离线归一化: 本地 models.dev api.json 文件路径")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    parser.add_argument("--check", action="store_true", help="只校验现有快照存在且可解析")
    args = parser.parse_args()

    out_path = Path(args.out)
    if args.check:
        if not out_path.is_file():
            print(f"[fail] 快照不存在: {out_path}", file=sys.stderr)
            return 1
        snapshot = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[ok] 快照可解析: {snapshot.get('model_count', '?')} 模型, generated_at={snapshot.get('generated_at')}")
        return 0

    if args.source:
        source = json.loads(Path(args.source).read_text(encoding="utf-8"))
        source_name = f"file:{args.source}"
    else:
        source = _fetch_models_dev()
        source_name = MODELS_DEV_URL

    snapshot = build_snapshot(source, source_name, OVERRIDES_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"[ok] 快照已生成: {snapshot['model_count']} 模型 (+{snapshot['override_count']} overrides) → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
