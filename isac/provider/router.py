"""J2 模型路由器 (SPECIFICATION.md 2.4)。

``ModelRouter.select()`` 接收所需 operation、输入/输出模态、Agent 授权矩阵、成本上限、
延迟目标和健康状态, 返回可解释的 ``ModelSelection``; 业务层不得按模型名硬编码能力。

骨架状态: operation + 模态 + 授权过滤已就位; 成本/延迟打分排序、健康探测、用户偏好与
回退链留待 J2 实现节点 (标注 TODO)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from isac.provider.catalog import ModelSelection

if TYPE_CHECKING:
    from isac.provider.catalog import ModelCatalog


class ModelRouter:
    """按能力需求选择模型。"""

    def __init__(self, catalog: ModelCatalog) -> None:
        self._catalog = catalog

    def select(
        self,
        *,
        operation: str,
        modalities_in: set[str] | None = None,
        modalities_out: set[str] | None = None,
        allowed_operations: set[str] | None = None,
        cost_ceiling: str | None = None,
        latency_target: str | None = None,
    ) -> ModelSelection | None:
        """选择满足 operation / 模态 / 授权的模型; 无候选返回 None。

        TODO(J2): 在过滤后按成本上限 / 延迟目标 / 健康状态打分排序, 支持用户偏好与
        能力回退链; 当前取第一个满足过滤条件的候选并给出匹配原因。
        """
        # Agent 授权: 未授权该 operation 直接无候选
        if allowed_operations is not None and operation not in allowed_operations:
            return None

        candidates = self._catalog.find_by_operation(operation)
        if modalities_in:
            candidates = [d for d in candidates if modalities_in <= d.modalities_in]
        if modalities_out:
            candidates = [d for d in candidates if modalities_out <= d.modalities_out]
        if not candidates:
            return None
        return ModelSelection(descriptor=candidates[0], reason=f"matched operation={operation}")
