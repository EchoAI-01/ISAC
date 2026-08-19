"""重试辅助: Retry-After 解析 (阶段3-1 M7)。

背景: 429 (限流) 响应常携带 ``Retry-After`` 头 (秒数或 HTTP 日期), 告诉客户端至少等
多久再重试。此前 LLM 侧与渠道出站都不读该头, 只按自己的指数退避盲目重试 —— 配额未
恢复就重发, 大概率再次 429。本模块提供统一的 ``parse_retry_after`` 供 LLM provider 与
各渠道适配器共用 (口径一致, 避免各写各的)。

只处理常见的"整数秒"形式 (绝大多数限流实现); HTTP 日期形式罕见且解析需引入 email.utils
日期解析, 收益低, 解析失败一律返回 None (回退调用方自己的退避策略), 绝不抛错。
"""

from __future__ import annotations

# 安全上限: 服务端可能返回异常大的 Retry-After (如 1 小时), 直接照等会让调用长时间
# 挂起; 封顶后既尊重服务端意图量级, 又不致阻塞。
MAX_RETRY_AFTER_SECONDS: float = 60.0


def parse_retry_after(value: str | None) -> float | None:
    """解析 ``Retry-After`` 头为秒数 (float); 不可解析/非正数返回 None。

    仅支持整数秒形式 (如 ``"3"`` / ``"120"``); 浮点、负数、HTTP 日期、空值一律返回
    None, 由调用方回退自身退避策略。结果封顶 ``MAX_RETRY_AFTER_SECONDS``。
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)
