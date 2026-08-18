"""U1 旧 sessions 数据迁移脚本: gateway/sessions.db → 会话事件流。

背景: U1 之前会话身份由 SessionManager 写穿到 ``gateway/sessions.db`` 的 sessions
表 (R5), 但**消息内容从未持久化** (每回合 LLM 只看当前 burst) —— 旧库里没有可迁移
的对话历史。U1 事件溯源内核让 ``session_events.db`` 成为会话的唯一时间线, 本脚本
把旧 sessions 表的会话身份逐分区迁移为一条 ``session.migrated`` ignorable 标记事件:

- 事件流保有迁移前会话的溯源凭证 (legacy session_id / 平台 / 群 / 活跃时间);
- ignorable 类型不参与历史重建 (fold 安全跳过), 不污染派生的聊天窗口;
- append-only: 只向事件流追加, 不改动/删除旧 sessions 表任何数据。

幂等: 事件流中已有事件的分区 (已迁移或 U1 后新建的会话) 跳过。

用法::

    python -m isac.session.migrate --data-dir data
    python -m isac.session.migrate --data-dir data --dry-run   # 只报告, 不写入
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from isac.session.event_store import SessionEventStore
from isac.session.models import EVENT_SESSION_MIGRATED, SessionEvent
from isac.utils.logger import get_logger

logger = get_logger(__name__)


def _read_legacy_sessions(legacy_db_path: Path) -> list[dict[str, Any]]:
    """同步读取旧 sessions 表全部行 (只读; 文件不存在返回空)。

    用 stdlib sqlite3 而非 aiosqlite —— 迁移脚本是一次性批处理, 且对旧库只读,
    不引入事件流 WAL 连接; 旧库无 WAL, 只读打开不干扰正在运行的主程序。
    """
    import sqlite3

    if not legacy_db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{legacy_db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT session_id, session_key, user_id, agent_id, platform, group_id, "
            "is_group, created_at, last_active, state FROM sessions"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


async def migrate_legacy_sessions(
    data_dir: str | Path, *, dry_run: bool = False
) -> dict[str, Any]:
    """把旧 sessions 表迁移为事件流中的 session.migrated 标记事件。

    返回报告: ``{"legacy_total", "migrated", "skipped_existing", "dry_run"}``。
    """
    data_path = Path(data_dir)
    legacy_db = data_path / "gateway" / "sessions.db"
    events_db = data_path / "gateway" / "session_events.db"

    legacy_rows = _read_legacy_sessions(legacy_db)
    report: dict[str, Any] = {
        "legacy_db": str(legacy_db),
        "legacy_total": len(legacy_rows),
        "migrated": 0,
        "skipped_existing": 0,
        "dry_run": dry_run,
    }
    if not legacy_rows:
        logger.info("U1 迁移: 旧 sessions 表为空或不存在, 无需迁移", path=str(legacy_db))
        return report

    store = SessionEventStore(str(events_db))
    await store.start()
    try:
        for row in legacy_rows:
            session_key = str(row.get("session_key") or "")
            if not session_key:
                continue
            if await store.max_seq(session_key) > 0:
                report["skipped_existing"] += 1
                continue
            if dry_run:
                report["migrated"] += 1
                continue
            await store.append(
                SessionEvent(
                    session_key=session_key,
                    event_type=EVENT_SESSION_MIGRATED,
                    # 用旧会话最后活跃时间作事件时间 (缺省取当前), 保持时间线语义。
                    timestamp=int(row.get("last_active") or time.time()),
                    payload={
                        "legacy_session_id": row.get("session_id"),
                        "agent_id": row.get("agent_id"),
                        "platform": row.get("platform"),
                        "group_id": row.get("group_id"),
                        "user_id": row.get("user_id"),
                        "is_group": bool(row.get("is_group")),
                        "created_at": row.get("created_at"),
                        "last_active": row.get("last_active"),
                        "state": row.get("state"),
                    },
                )
            )
            report["migrated"] += 1
        await store.flush()
    finally:
        await store.stop()
    logger.info(
        "U1 迁移完成",
        legacy_total=report["legacy_total"],
        migrated=report["migrated"],
        skipped=report["skipped_existing"],
        dry_run=dry_run,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="U1 旧 sessions 数据迁移到会话事件流")
    parser.add_argument("--data-dir", default="data", help="ISAC 数据目录 (默认 data)")
    parser.add_argument("--dry-run", action="store_true", help="只报告将迁移的数量, 不写入")
    args = parser.parse_args(argv)
    report = asyncio.run(migrate_legacy_sessions(args.data_dir, dry_run=args.dry_run))
    print(
        f"legacy_total={report['legacy_total']} migrated={report['migrated']} "
        f"skipped_existing={report['skipped_existing']} dry_run={report['dry_run']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
