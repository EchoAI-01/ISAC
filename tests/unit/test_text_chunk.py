"""Fix-98: 出站文本分段单元测试 (Telegram 4096 / Discord 2000 上限)。"""

from __future__ import annotations

from isac.channel.text_chunk import chunk_text


def test_short_text_single_chunk() -> None:
    assert chunk_text("hello", 4096) == ["hello"]


def test_empty_text_returns_empty_list() -> None:
    assert chunk_text("", 4096) == []


def test_exact_limit_single_chunk() -> None:
    text = "x" * 4096
    assert chunk_text(text, 4096) == [text]


def test_splits_preserving_newline_boundaries() -> None:
    # 三行各 5 字符 (含换行), 上限 11 → 每段最多两行
    text = "aaaaa\nbbbbb\nccccc\n"
    chunks = chunk_text(text, 11)
    assert all(len(c) <= 11 for c in chunks)
    assert "".join(chunks) == text  # 分段重组不丢内容


def test_hard_split_oversized_single_line() -> None:
    text = "x" * 100  # 单行超限, 无换行可切
    chunks = chunk_text(text, 30)
    assert all(len(c) <= 30 for c in chunks)
    assert "".join(chunks) == text
    assert len(chunks) == 4  # 30+30+30+10


def test_long_reply_chunked_for_discord_limit() -> None:
    # 模拟超长回复 (5000 字符) 按 Discord 2000 切分
    text = "段落内容。\n" * 500  # 每行 6 字符
    chunks = chunk_text(text, 2000)
    assert len(chunks) > 1
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == text
