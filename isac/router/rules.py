"""路由规则持久化 (data/routing.jsonc) 与热更新。"""

from __future__ import annotations

import json
from pathlib import Path

from isac.router.types import ChannelBinding, RoutingRules
from isac.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import json5

    _loads = json5.loads
except ImportError:  # pragma: no cover
    _loads = json.loads


def load_rules(path: str | Path) -> RoutingRules:
    """从 JSONC 文件加载路由规则；文件不存在返回空规则。"""
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("路由规则文件不存在，使用空规则", path=str(file_path))
        return RoutingRules()
    raw = _loads(file_path.read_text(encoding="utf-8"))
    return RoutingRules(
        bindings=[ChannelBinding(**b) for b in raw.get("bindings", [])],
        default_agents=dict(raw.get("default_agents", {})),
    )


def save_rules(path: str | Path, rules: RoutingRules) -> None:
    """保存路由规则到 JSONC 文件。"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    raw = {
        "bindings": [
            {
                "platform": b.platform,
                "agent_id": b.agent_id,
                "group_id": b.group_id,
                "user_id": b.user_id,
            }
            for b in rules.bindings
        ],
        "default_agents": rules.default_agents,
    }
    file_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("路由规则已保存", path=str(file_path))
