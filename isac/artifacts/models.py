"""J2 多模态 IO 数据契约 (SPECIFICATION.md 2.4)。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MediaInput:
    """多模态输入媒体的受控引用 (经 MediaNormalizer 校验后使用)。

    二进制内容通过 ``uri`` (本地路径或受控 URL) 间接引用, 不直接嵌入历史/日志。
    """

    kind: str  # image | audio | video
    uri: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0
    source: str = ""  # 来源标识 (用户上传 / Channel / 生成)
    metadata: dict = field(default_factory=dict)


@dataclass
class ArtifactRef:
    """多模态生成制品的受控引用; 二进制内容不写入消息历史、日志或记忆。"""

    artifact_id: str
    kind: str  # image | audio | video | file
    mime_type: str = ""
    uri: str = ""  # 受控下载 / 访问地址
    size_bytes: int = 0
    duration_seconds: float = 0.0
    created_at: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class TranscriptionResult:
    """语音转写 (STT) 结果。"""

    text: str
    language: str = ""
    duration_seconds: float = 0.0
    segments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class MediaAnalysisResult:
    """视觉 / 视频理解结果。"""

    text: str
    labels: list[str] = field(default_factory=list)
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
