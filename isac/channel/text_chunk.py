"""出站文本分段 (Fix-98)。

Telegram 单条文本上限 4096 字符、Discord 2000 字符; 超长回复若整条提交, 平台
返回 400 → send False → 用户完全收不到回复 (日志只有一条"发送失败")。按平台上限
分段发送, 优先在换行边界切分保证可读性; 单行超长则硬切。
"""

from __future__ import annotations


def chunk_text(text: str, max_chars: int) -> list[str]:
    """把 text 切成每段 ≤ max_chars 的列表, 优先换行边界, 空输入返回 []。

    策略: 逐行累积, 当前段加上新行将超限时先收口当前段; 单行本身超限时按
    max_chars 硬切。保留换行符在段尾 (可读性), 不产生空段。
    """
    if not text or max_chars <= 0:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        # 单行超限: 先收口当前段, 再硬切该行
        if len(line) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), max_chars):
                chunks.append(line[i : i + max_chars])
            continue
        if len(current) + len(line) > max_chars:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks
