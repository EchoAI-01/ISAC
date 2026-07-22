"""ISAC 全局常量。

可调参数应放入配置文件 (SPECIFICATION.md 3.1)，此处只放框架级常量。
"""

# 门控 (ARCHITECTURE.md 3.7)
REPLY_NECESSITY_THRESHOLD = 80

# 门控回复必要性评分权重 (ARCHITECTURE.md 3.7)。
# 框架级默认值；后续可迁入配置 (config.gating) 做 Agent 级覆盖。
GATING_BASE_SCORE_AT = 100  # 被 @
GATING_BASE_SCORE_MENTION = 80  # 文本提及 Bot 名
GATING_BASE_SCORE_PRIVATE = 40  # 私聊
GATING_BASE_SCORE_FOCUS = 40  # 专注模式
GATING_CONTENT_QUESTION = 15  # 疑问句
GATING_CONTENT_REQUEST = 20  # 请求/委托
GATING_CONTENT_CONSULT = 20  # 征询意见 (需 @ 或提及)
GATING_CONTENT_LONG_TEXT = 5  # 长文本 (> 120 字)
GATING_CONTENT_LONG_TEXT_EXTRA = 10  # 超长文本 (> 240 字)
GATING_LONG_TEXT_THRESHOLD = 120
GATING_LONG_TEXT_THRESHOLD_EXTRA = 240
GATING_CONTENT_SHORT_REACTION = -25  # 短反应 (<= 5 字且无问询信号)
GATING_SHORT_REACTION_MAX_LEN = 5
GATING_PRESSURE_PER_PENDING = 15  # 每条积压消息的压力分
GATING_PRESSURE_CAP = 100  # 压力分上限
GATING_PRESENCE_PENALTY_MAX = 25  # 存在感惩罚上限 (近窗口本 Agent 发言占比)
GATING_FREQUENCY_MIN = 0.5  # 频率系数下限
GATING_FREQUENCY_MAX = 1.0  # 频率系数上限

# 疑问 / 请求 / 征询 关键词 (中文为主，英文标点通用)
GATING_QUESTION_MARKERS = ("?", "？", "吗", "呢", "什么", "怎么", "为什么", "如何", "哪", "谁", "多少", "几")
GATING_REQUEST_MARKERS = ("请", "帮我", "帮忙", "能不能", "可以吗", "麻烦", "求")
GATING_CONSULT_MARKERS = ("你觉得", "怎么看", "好不好", "行不行", "选哪个", "你说呢", "有没有建议", "给点建议")

# Prompt 预算 (ARCHITECTURE.md 3.4)
DEFAULT_PROMPT_TOKEN_BUDGET = 8000

# 记忆 (ARCHITECTURE.md 3.6)
SHARED_MEMORY_NAMESPACE = "shared"  # 跨 Agent 共享记忆命名空间保留值
HEURISTIC_MEMORY_COOLDOWN_SECONDS = 180  # 启发式记忆冷却 (3 分钟)
HEURISTIC_MEMORY_MIN_NEW_MESSAGES = 60  # 启发式记忆最小新消息数

# 多 Agent (ARCHITECTURE.md 3.1)
DEFAULT_AGENT_ID = "default"  # 单 Agent 兼容模式使用的默认 ID

# 控制面 (ARCHITECTURE.md 3.9)
DEFAULT_CONTROL_HOST = "127.0.0.1"
DEFAULT_CONTROL_PORT = 8765
