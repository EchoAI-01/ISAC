"""R4 记忆完整性补齐单测 (行话学习 + 中期记忆 COMPRESS)。

覆盖:
- R4-① ``_extract_jargon_step``: 群聊高频词经 LLM 释义写入 jargon; 无群聊/LLM=None 时跳过;
  ``_top_candidate_words`` 高频词统计 (去停用词/单字/既有 jargon)。
- R4-② COMPRESS 回调入队 + consolidator ``_compress_step`` LLM 摘要落盘 episodes.summary
  + ``MidTermMemoryInjector.build`` 读已落盘 summary 注入 RecallCue; 无 summary 时降级空串。
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from isac.core.types import InjectionContext, LLMResponse
from isac.gateway.models import Session, UserProfile
from isac.memory.consolidator import (
    MemoryConsolidator,
    _format_session_transcript,
    _parse_jargon_response,
    _top_candidate_words,
)
from isac.memory.injector.mid_term import MidTermMemoryInjector
from isac.memory.storage.metadata import MetadataStore


@dataclass
class _Msg:
    content: str = "?"


def _ctx_for_session(session_id: str) -> InjectionContext:
    """构造带指定 session_id 的 InjectionContext (current_message 用鸭子类型)。"""
    return InjectionContext(
        session=Session(session_id=session_id, user_id="u1", agent_id="a1", platform="web"),
        user_profile=UserProfile(user_id="u1", nickname="测试"),
        current_message=_Msg(content="?"),  # type: ignore[arg-type]
        pending_messages=[_Msg(content="?")],  # type: ignore[list-item]
        timestamp=time.time(),
    )


def _connect(store: MetadataStore) -> aiosqlite.Connection:
    return aiosqlite.connect(store.db_path)


async def _make_store(tmp_path: str) -> MetadataStore:
    store = MetadataStore(tmp_path)
    await store.init_schema()
    return store


@pytest.fixture
async def store() -> MetadataStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    s = await _make_store(tmp.name)
    yield s
    await asyncio.to_thread(lambda: Path(tmp.name).unlink(missing_ok=True))


class _ScriptedLLM:
    """按调用顺序返回预设响应的假 LLM (记录所有调用)。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "kwargs": kwargs})
        text = self._responses.pop(0) if self._responses else ""
        return LLMResponse(content=text)


class _BoomLLM:
    async def chat(self, system: str, messages: list[dict], **kwargs: Any) -> LLMResponse:
        raise RuntimeError("LLM down")


async def _store_group_episode(
    store: MetadataStore, eid: str, group: str, content: str, *, user_id: str = ""
) -> None:
    await store.store_episode("a1", {
        "id": eid, "session_id": "s1", "user_id": user_id,
        "group_id": group, "content": content,
    })


# ── R4-① 行话学习 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_candidate_words_filters_stopwords_and_single(store: MetadataStore) -> None:
    """高频词统计: 去停用词/单字/既有 jargon, 保留高频英文整词与中文 bigram。"""
    texts = [
        "今天 k8s 集群 k8s 部署",
        "k8s 集群 k8s 稳定",
        "嗯 啊 的 了 k8s",
    ]
    cands = _top_candidate_words(texts, existing=set())
    # "k8s" 出现 6 次 (≥ DEFAULT_JARGON_MIN_FREQ=3), 应在候选首位
    assert "k8s" in cands
    assert cands[0] == "k8s"
    # 单字与停用词不应出现
    assert "嗯" not in cands
    assert "的" not in cands


@pytest.mark.asyncio
async def test_top_candidate_words_excludes_existing_jargon() -> None:
    """既存 jargon 词被排除 (避免重复释义)。"""
    texts = ["k8s k8s k8s"]  # 频次 3
    cands = _top_candidate_words(texts, existing={"k8s"})
    assert "k8s" not in cands


def test_parse_jargon_response_extracts_meaning_context() -> None:
    """解析 MEANING:/CONTEXT: 两行格式。"""
    meaning, context = _parse_jargon_response("MEANING: 容器编排系统\nCONTEXT: 部署集群时用")
    assert meaning == "容器编排系统"
    assert context == "部署集群时用"


def test_parse_jargon_response_unknown_returns_empty() -> None:
    """LLM 回复「未知」时 meaning 命中未知哨兵, 调用方据此不写回。"""
    meaning, _ = _parse_jargon_response("MEANING: 未知\nCONTEXT: 无")
    assert meaning == "未知"


@pytest.mark.asyncio
async def test_extract_jargon_writes_high_freq_word(store: MetadataStore) -> None:
    """群聊高频词 k8s 经 LLM 释义 → upsert_jargon 写入; jargon_extracted≥1。"""
    # 3 条群聊 episode, k8s 高频出现 (≥ DEFAULT_JARGON_MIN_FREQ)
    for i in range(3):
        await _store_group_episode(store, f"ep{i}", "g1", "我们用 k8s 部署 k8s 集群, k8s 很稳定")
    llm = _ScriptedLLM(responses=["MEANING: 容器编排系统\nCONTEXT: 部署集群时用"])
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=llm)
    result = await consolidator.run_once()
    assert result.jargon_extracted >= 1
    entries = await store.list_jargon("a1")
    words = [e["word"] for e in entries]
    assert "k8s" in words


@pytest.mark.asyncio
async def test_extract_jargon_skips_when_no_group_episodes(store: MetadataStore) -> None:
    """无私聊 (无 group_id) → 行话学习跳过, jargon_extracted=0。"""
    await store.store_episode("a1", {
        "id": "ep0", "session_id": "s1", "user_id": "", "content": "k8s k8s k8s",
    })
    llm = _ScriptedLLM(responses=[])
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=llm)
    result = await consolidator.run_once()
    assert result.jargon_extracted == 0
    assert llm.calls == []  # 无群聊 + 无 user → 不调 LLM 释义/画像


@pytest.mark.asyncio
async def test_extract_jargon_skipped_when_llm_none(store: MetadataStore) -> None:
    """LLM 未注入 → 行话学习步骤整体跳过 (run_once LLM 守卫外)。"""
    for i in range(3):
        await _store_group_episode(store, f"ep{i}", "g1", "k8s k8s k8s")
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=None)
    result = await consolidator.run_once()
    assert result.jargon_extracted == 0
    entries = await store.list_jargon("a1")
    assert entries == []


@pytest.mark.asyncio
async def test_extract_jargon_llm_failure_isolated(store: MetadataStore) -> None:
    """LLM 释义失败仅跳过该词, 不拖垮整合 (异常隔离)。"""
    for i in range(3):
        await _store_group_episode(store, f"ep{i}", "g1", "k8s k8s k8s")
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=_BoomLLM())
    result = await consolidator.run_once()
    assert result.jargon_extracted == 0  # 释义失败, 未写入
    entries = await store.list_jargon("a1")
    assert entries == []


# ── R4-② 中期记忆 COMPRESS ────────────────────────────────────────


def test_format_session_transcript_truncates() -> None:
    """transcript 截断到上限 + dict 消息按 role 格式化。"""
    msgs = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "在的"},
        "纯文本片段",
    ]
    out = _format_session_transcript(msgs, max_chars=15)
    assert "[user] 你好" in out
    assert len(out) <= 15 + 20  # 容许单条截断后的少量格式开销


@pytest.mark.asyncio
async def test_enqueue_then_compress_writes_summary(store: MetadataStore) -> None:
    """入队会话快照 → run_once _compress_step LLM 摘要 → episodes.summary 落盘。"""
    # 先落盘一条 episode (供 latest_episode_id_for_session 命中); user_id 留空避免
    # 画像归纳步骤抢占 scripted LLM 响应 (本测试聚焦压缩链路)
    await store.store_episode("a1", {
        "id": "ep1", "session_id": "sess-a", "user_id": "", "content": "原始会话内容",
    })
    llm = _ScriptedLLM(responses=["这是会话的关键摘要。"])
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=llm)
    # COMPRESS 回调仅入队 (不调 LLM)
    await consolidator.enqueue_compression(
        "sess-a", [{"role": "user", "content": "讨论了部署方案"}, {"role": "assistant", "content": "好的"}],
        context="agent=a1",
    )
    assert llm.calls == []  # 入队阶段不调 LLM
    # run_once 消费队列, LLM 摘要落盘
    result = await consolidator.run_once()
    assert result.compressed_summaries == 1
    assert len(llm.calls) == 1  # 摘要调了一次 LLM
    ep_id = await store.latest_episode_id_for_session("a1", "sess-a")
    summary = await store.get_episode_summary("a1", ep_id)
    assert summary == "这是会话的关键摘要。"


@pytest.mark.asyncio
async def test_compress_dedup_same_session_overwrites(store: MetadataStore) -> None:
    """同 session_id 重复入队 → 未消费时覆盖最新快照 (只摘要一次)。"""
    await store.store_episode("a1", {
        "id": "ep1", "session_id": "sess-b", "user_id": "", "content": "内容",
    })
    llm = _ScriptedLLM(responses=["摘要。"])
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=llm)
    await consolidator.enqueue_compression("sess-b", [{"role": "user", "content": "旧快照"}])
    await consolidator.enqueue_compression("sess-b", [{"role": "user", "content": "新快照"}])
    result = await consolidator.run_once()
    assert result.compressed_summaries == 1  # 只处理一份快照
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_compress_skipped_when_no_episode_for_session(store: MetadataStore) -> None:
    """会话无落盘 episode → _compress_step 解析为空, 无处写回, compressed_summaries=0。"""
    # 存一条另一会话的 episode (保证 episodes 非空, run_once 不早退, 真正走到 _compress_step)
    await store.store_episode("a1", {
        "id": "ep-other", "session_id": "sess-other", "user_id": "", "content": "无关",
    })
    llm = _ScriptedLLM(responses=["摘要。"])
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=llm)
    await consolidator.enqueue_compression("sess-none", [{"role": "user", "content": "无落盘"}])
    result = await consolidator.run_once()
    assert result.compressed_summaries == 0  # sess-none 无 episode, 摘要丢弃


@pytest.mark.asyncio
async def test_compress_skipped_when_llm_none(store: MetadataStore) -> None:
    """LLM 未注入 → 压缩步骤整体跳过 (run_once LLM 守卫外)。"""
    await store.store_episode("a1", {
        "id": "ep1", "session_id": "sess-c", "user_id": "u1", "content": "内容",
    })
    consolidator = MemoryConsolidator(agent_id="a1", namespace="a1", metadata=store, llm=None)
    await consolidator.enqueue_compression("sess-c", [{"role": "user", "content": "x"}])
    result = await consolidator.run_once()
    assert result.compressed_summaries == 0


@pytest.mark.asyncio
async def test_mid_term_injector_reads_summary(store: MetadataStore) -> None:
    """MidTermMemoryInjector.build 读已落盘 summary 注入 RecallCue, 不再复述 pending。"""
    await store.store_episode("a1", {
        "id": "ep1", "session_id": "sess-inj", "user_id": "u1", "content": "原始",
        "summary": "此前讨论了发布流程与回滚预案。",
    })
    pipeline = type("P", (), {"metadata": store})()
    inj = MidTermMemoryInjector(pipeline)  # type: ignore[arg-type]
    ctx = _ctx_for_session("sess-inj")
    out = await inj.build(ctx)
    assert "此前讨论了发布流程与回滚预案" in out
    assert "中期记忆-内部参考" in out
    # 不再出现旧实现的 pending_messages 截断复述标题
    assert "尚未处理" not in out


@pytest.mark.asyncio
async def test_mid_term_injector_empty_when_no_summary(store: MetadataStore) -> None:
    """无落盘 summary → build 返回空串 (零行为变化, 降级不注入)。"""
    await store.store_episode("a1", {
        "id": "ep1", "session_id": "sess-empty", "user_id": "u1", "content": "原始",
    })  # 无 summary
    pipeline = type("P", (), {"metadata": store})()
    inj = MidTermMemoryInjector(pipeline)  # type: ignore[arg-type]
    out = await inj.build(_ctx_for_session("sess-empty"))
    assert out == ""


@pytest.mark.asyncio
async def test_mid_term_injector_empty_when_no_metadata() -> None:
    """pipeline 无 metadata → build 返回空串 (不报错)。"""
    pipeline = type("P", (), {})()  # 无 metadata 属性
    inj = MidTermMemoryInjector(pipeline)  # type: ignore[arg-type]
    assert await inj.build(_ctx_for_session("sess-x")) == ""
