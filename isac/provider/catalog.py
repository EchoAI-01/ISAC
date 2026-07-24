"""J2 模型能力目录 (SPECIFICATION.md 2.4)。

所有 Provider 返回 ``ModelDescriptor`` 由 ``ModelCatalog`` 注册; ``ModelRouter``
(见 router.py) 据此选择模型。业务层不得按模型名硬编码能力。

骨架状态: 描述符契约 + 注册/查询接口就位; 健康状态、动态注册与远程同步留待实现节点。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelDescriptor:
    """可发现、可授权、可路由的模型能力描述。"""

    provider_id: str
    model_id: str
    modalities_in: set[str] = field(default_factory=set)  # text | image | audio | video
    modalities_out: set[str] = field(default_factory=set)  # text | image | audio | video | embedding | score
    operations: set[str] = field(default_factory=set)  # chat | vision | embed | rerank | stt | tts | image_gen | ...
    supports_tools: bool = False
    supports_streaming: bool = False
    max_input_bytes: int | None = None
    max_duration_seconds: float | None = None
    cost_tier: str = "unknown"
    latency_tier: str = "standard"
    safety_tags: set[str] = field(default_factory=set)
    extra: dict = field(default_factory=dict)


@dataclass
class ModelSelection:
    """ModelRouter 的可解释选择结果。"""

    descriptor: ModelDescriptor
    reason: str = ""
    fallback_used: bool = False


class ModelCatalog:
    """模型能力目录: 注册 / 查询可用模型能力声明。"""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], ModelDescriptor] = {}

    def register(self, descriptor: ModelDescriptor) -> None:
        """登记一个模型能力描述符 (provider_id + model_id 唯一)。"""
        self._by_key[(descriptor.provider_id, descriptor.model_id)] = descriptor

    def get(self, provider_id: str, model_id: str) -> ModelDescriptor | None:
        """按 (provider_id, model_id) 查询; 未注册返回 None。"""
        return self._by_key.get((provider_id, model_id))

    def list_all(self) -> list[ModelDescriptor]:
        """返回全部已注册描述符。"""
        return list(self._by_key.values())

    def find_by_operation(self, operation: str) -> list[ModelDescriptor]:
        """返回支持指定 operation 的全部描述符。"""
        return [d for d in self._by_key.values() if operation in d.operations]
