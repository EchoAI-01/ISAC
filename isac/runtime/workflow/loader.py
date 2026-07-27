"""声明式工作流加载 (S5, DEVELOPMENT_PLAN.md §四 P5/O3)。

从 ``<base_dir>/*.json`` 扫描并解析为 ``Workflow`` (workflow_id/name/stages/
transitions), 调 ``engine.register(...)`` 登记。单个文件解析失败只记 warning
跳过, 不阻塞其余文件加载。返回成功加载数 (供调用方观测)。

文件 schema 与 ``Workflow`` dataclass 字段对齐::

    {
        "workflow_id": "wf1",
        "name": "示例",
        "stages": [
            {"stage_id": "s1", "action": "tool:foo", "params": {"agent_id": "a1"}}
        ],
        "transitions": [
            {"from_stage": "s1", "to_stage": "s2", "kind": "sequential"}
        ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.runtime.workflow.models import Stage, StageStatus, Transition, TransitionKind, Workflow, WorkflowStatus
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.workflow.engine import WorkflowEngine

logger = get_logger(__name__)


def load_workflows_from_dir(engine: WorkflowEngine, base_dir: str) -> int:
    """扫描 ``base_dir/*.json`` 加载所有工作流定义到 engine。

    单个文件解析失败只记 warning 跳过, 不阻塞其余文件; 返回成功加载数。
    """
    dir_path = Path(base_dir)
    if not dir_path.is_dir():
        logger.info("工作流定义目录不存在, 跳过声明式加载", path=base_dir)
        return 0
    loaded = 0
    for json_path in sorted(dir_path.glob("*.json")):
        try:
            workflow = _parse_workflow_file(json_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("工作流定义解析失败, 已跳过", path=str(json_path), error=str(exc))
            continue
        if workflow is None:
            continue
        engine.register(workflow)
        loaded += 1
        logger.info("已加载工作流定义", workflow_id=workflow.workflow_id, path=str(json_path))
    return loaded


def _parse_workflow_file(path: Path) -> Workflow | None:
    """解析单个 JSON 文件为 Workflow (格式不符时返回 None 或抛 ValueError)。"""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"工作流定义 {path} 不是 JSON 对象")
    workflow_id = str(data.get("workflow_id", "")).strip()
    if not workflow_id:
        raise ValueError(f"工作流定义 {path} 缺少 workflow_id")
    stages = [
        Stage(
            stage_id=str(s.get("stage_id", "")),
            action=str(s.get("action", "")),
            params=dict(s.get("params", {}) or {}),
        )
        for s in (data.get("stages") or [])
        if isinstance(s, dict) and s.get("stage_id")
    ]
    transitions = [
        Transition(
            from_stage=str(t.get("from_stage", "")),
            to_stage=str(t.get("to_stage", "")),
            kind=_parse_transition_kind(t.get("kind")),
            condition=str(t.get("condition", "") or ""),
        )
        for t in (data.get("transitions") or [])
        if isinstance(t, dict) and t.get("from_stage") and t.get("to_stage")
    ]
    # workflow_id 必填; status 默认 PENDING; metadata 透传
    wf = Workflow(
        workflow_id=workflow_id,
        name=str(data.get("name", "") or ""),
        stages=stages,
        transitions=transitions,
        metadata=dict(data.get("metadata", {}) or {}),
    )
    # 重置运行态 (从文件加载的定义视为未启动)
    wf.status = WorkflowStatus.PENDING
    for s in wf.stages:
        s.status = StageStatus.PENDING
    return wf


def _parse_transition_kind(kind_str: Any) -> TransitionKind:
    """解析 transition.kind 字符串 (默认 SEQUENTIAL)。"""
    s = str(kind_str or "sequential").lower().strip()
    for k in TransitionKind:
        if k.value == s:
            return k
    return TransitionKind.SEQUENTIAL
