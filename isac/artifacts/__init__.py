"""J2 多模态制品与媒体 IO 值对象 (SPECIFICATION.md 2.4)。

``MediaInput`` 是进入 MediaNormalizer 校验后的受控输入引用; ``ArtifactRef`` 是生成
制品的受控引用。二进制内容不得直接塞入对话历史、日志或记忆 —— 只传引用。

骨架状态: 数据契约 + ArtifactStore 接口就位; 真实存储后端 (对象存储/签名 URL/TTL)
与 MediaNormalizer 校验留待 J2 实现节点。
"""

from __future__ import annotations

from isac.artifacts.models import ArtifactRef, MediaAnalysisResult, MediaInput, TranscriptionResult
from isac.artifacts.store import ArtifactStore

__all__ = [
    "ArtifactRef",
    "ArtifactStore",
    "MediaAnalysisResult",
    "MediaInput",
    "TranscriptionResult",
]
