"""会话与用户数据模型 (SPECIFICATION.md 1.2 / 1.3)。"""

from __future__ import annotations

from dataclasses import dataclass, field

from isac.channel.model import ISACMessage
from isac.core.types import Budget


@dataclass
class SessionContext:
    """会话运行时上下文 (不持久化)"""

    budget: Budget  # LLM 调用预算
    interrupt_requested: bool = False  # 是否请求中断
    iteration: int = 0  # 当前迭代次数
    reasoning_content: str = ""  # 推理内容
    pending_messages: list[ISACMessage] = field(default_factory=list)


@dataclass
class Session:
    """ISAC 会话"""

    session_id: str  # 全局唯一会话 ID
    user_id: str  # 主用户 ID (跨平台统一)
    user_ids: dict[str, str] = field(default_factory=dict)  # 各平台 user_id 映射
    agent_id: str = ""  # 所属 Agent (多 Agent 架构)
    platform: str = ""  # 当前交互平台
    group_id: str | None = None  # 群聊 ID
    is_group: bool = False  # 是否群聊

    created_at: int = 0  # 创建时间
    last_active: int = 0  # 最后活跃时间
    state: str = "active"  # "active" | "idle" | "closed"

    # 运行时状态 (不持久化)
    context: SessionContext | None = None


@dataclass
class UserProfile:
    """用户画像 (跨平台统一)"""

    user_id: str  # 主用户 ID
    platform_ids: dict[str, str] = field(default_factory=dict)  # 各平台 ID 映射

    nickname: str = ""  # 昵称
    relationship_depth: float = 0.0  # 关系深度 0.0~1.0
    interaction_count: int = 0  # 交互次数
    first_seen: int = 0
    last_seen: int = 0

    # 行为特征
    expression_style: dict = field(default_factory=dict)  # 表达风格偏好
    preferences: dict = field(default_factory=dict)  # 话题/回复偏好
    behavior_patterns: list[dict] = field(default_factory=list)

    # 内容特征
    jargon_set: list[str] = field(default_factory=list)  # 用户常用行话
    topics_of_interest: list[str] = field(default_factory=list)

    # 嵌入
    embedding: list[float] | None = None  # 用户画像向量
