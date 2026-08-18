"""U7 Agent 数据化专项测试 (prompt 文件化 + 能力快照 + category 路由)。

验收覆盖 (DEVELOPMENT_PLAN §四 U7):
- 新增一个模型族 = 加一个文件 (variant 变体选择零代码);
- 能力快照 drift CI 报警 (committed 快照新鲜度 + schema 检查);
- category 路由委派选型 (问答/创作/工具密集/闲聊四档);
- fallback 链按能力与可达性过滤 (requires_tools + record_health 接线)。
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from isac.agent.prompt_files import (
    FilePromptInjector,
    load_prompt_dir,
    model_family_of,
    parse_frontmatter,
)
from isac.core.exceptions import LLMError, RateLimitError
from isac.core.types import LLMResponse, TokenUsage
from isac.provider.capabilities import CapabilitySnapshot
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.category_routing import profile_for, select_for_category
from isac.provider.manager import ProviderManager
from isac.provider.router import ModelRouter
from isac.runtime.services import ServiceContainer
from isac.runtime.subagent.models import SubAgentTask
from isac.runtime.subagent.runner import _select_llm_for_task

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = REPO_ROOT / "data" / "model_capabilities.json"
GEN_SCRIPT = REPO_ROOT / "scripts" / "gen_model_capabilities.py"


def _load_generator() -> Any:
    """以文件路径加载生成脚本 (scripts/ 非包, importlib 直载)。"""
    spec = importlib.util.spec_from_file_location("gen_model_capabilities", GEN_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── ① prompt 文件化 ──────────────────────────────────────────


def test_parse_frontmatter_meta_and_body() -> None:
    text = "---\nfamily: persona\nvariant: claude\npriority: 90\nenabled: true\ntags: [a, b]\n---\n正文内容"
    meta, body = parse_frontmatter(text)
    assert meta["family"] == "persona"
    assert meta["variant"] == "claude"
    assert meta["priority"] == 90
    assert meta["enabled"] is True
    assert meta["tags"] == ["a", "b"]
    assert body == "正文内容"


def test_parse_frontmatter_missing_or_unclosed() -> None:
    meta, body = parse_frontmatter("纯正文无 frontmatter")
    assert meta == {} and body == "纯正文无 frontmatter"
    meta2, body2 = parse_frontmatter("---\nfamily: x\n未闭合")
    assert meta2 == {} and body2.startswith("---")  # 未闭合按普通正文


def test_model_family_of_prefix_override_unknown() -> None:
    assert model_family_of("gpt-4o-mini") == "gpt"
    assert model_family_of("claude-sonnet-4-5") == "claude"
    assert model_family_of("deepseek-chat") == "deepseek"
    assert model_family_of("some-unknown-model") == "default"
    assert model_family_of("gpt-4o-mini", override="custom_fam") == "custom_fam"


def test_load_prompt_dir_groups_and_skips(tmp_path: Path) -> None:
    (tmp_path / "persona_default.md").write_text(
        "---\nfamily: persona\npriority: 100\n---\n默认人格", encoding="utf-8"
    )
    (tmp_path / "persona_claude.md").write_text(
        "---\nfamily: persona\nvariant: claude\n---\nClaude 人格", encoding="utf-8"
    )
    (tmp_path / "rules.md").write_text("---\nfamily: rules\n---\n规则块", encoding="utf-8")
    (tmp_path / "bad_no_family.md").write_text("---\nvariant: x\n---\n无家族", encoding="utf-8")
    (tmp_path / "empty_body.md").write_text("---\nfamily: rules\n---\n", encoding="utf-8")
    (tmp_path / "not_md.txt").write_text("忽略", encoding="utf-8")

    grouped = load_prompt_dir(tmp_path)
    assert set(grouped.keys()) == {"persona", "rules"}
    assert len(grouped["persona"]) == 2
    assert grouped["persona"][0].variant == "default"  # default 变体排前
    assert len(grouped["rules"]) == 1
    # 缺失目录 → 空 (调用方落回 config 路径)
    assert load_prompt_dir(tmp_path / "nope") == {}


@pytest.mark.asyncio
async def test_file_prompt_injector_variant_selection(tmp_path: Path) -> None:
    (tmp_path / "p_default.md").write_text("---\nfamily: persona\n---\n默认人格", encoding="utf-8")
    (tmp_path / "p_claude.md").write_text("---\nfamily: persona\nvariant: claude\n---\nClaude 人格", encoding="utf-8")
    docs = load_prompt_dir(tmp_path)["persona"]

    inj_claude = FilePromptInjector("persona", docs, lambda: "claude")
    assert await inj_claude.build(None) == "Claude 人格"  # type: ignore[arg-type]
    inj_unknown = FilePromptInjector("persona", docs, lambda: "gemini")
    assert await inj_unknown.build(None) == "默认人格"  # type: ignore[arg-type]
    inj_boom = FilePromptInjector("persona", docs, lambda: (_ for _ in ()).throw(RuntimeError()))
    assert await inj_boom.build(None) == "默认人格"  # type: ignore[arg-type]
    assert inj_claude.key == "file_prompt:persona"

    # 全 disabled → 空注入
    for doc in docs:
        doc.enabled = False
    inj_off = FilePromptInjector("persona", docs, lambda: "claude")
    assert await inj_off.build(None) == ""  # type: ignore[arg-type]


# ── ② 模型能力快照 ───────────────────────────────────────────


def test_snapshot_load_missing_and_corrupt(tmp_path: Path) -> None:
    empty = CapabilitySnapshot.load(tmp_path / "nope.json")
    assert len(empty) == 0 and not empty.fresh()
    broken = tmp_path / "broken.json"
    broken.write_text("{invalid", encoding="utf-8")
    assert len(CapabilitySnapshot.load(broken)) == 0


def test_snapshot_get_case_insensitive_and_fields() -> None:
    snap = CapabilitySnapshot.from_dict(
        {
            "generated_at": "2026-08-17T00:00:00+00:00",
            "models": {
                "OpenAI/GPT-4o-mini": {
                    "context_window": 128000,
                    "supports_tools": True,
                    "modalities_in": ["text", "image"],
                    "cost_tier": "low",
                }
            },
        }
    )
    cap = snap.get("openai", "gpt-4o-mini")
    assert cap is not None
    assert cap.supports_tools is True
    assert cap.context_window == 128000
    assert cap.modalities_in == {"text", "image"}
    assert snap.get("openai", "gpt-4o") is None


def test_snapshot_freshness() -> None:
    now = datetime.now(UTC)
    fresh_snap = CapabilitySnapshot(generated_at=now.isoformat())
    assert fresh_snap.fresh(60, now=now) is True
    stale = CapabilitySnapshot(generated_at=(now - timedelta(days=61)).isoformat())
    assert stale.fresh(60, now=now) is False
    assert CapabilitySnapshot(generated_at="").fresh() is False
    assert CapabilitySnapshot(generated_at="not-a-date").fresh() is False


def test_generator_normalize_and_overrides(tmp_path: Path) -> None:
    gen = _load_generator()
    raw = {
        "openai": {
            "models": {
                "gpt-test": {
                    "limit": {"context": 100000},
                    "tool_call": True,
                    "attachment": True,
                    "cost": {"input": 1.0},
                },
                "weird": "not-a-dict",
            }
        },
        "bad-provider": "not-a-dict",
    }
    models = gen.normalize(raw)
    entry = models["openai/gpt-test"]
    assert entry["context_window"] == 100000
    assert entry["supports_tools"] is True
    assert "image" in entry["modalities_in"]
    assert "x_cost" in entry

    overrides = tmp_path / "overrides.json"
    overrides.write_text('{"zhipu/glm-x": {"supports_tools": true}}', encoding="utf-8")
    merged = gen.merge_overrides(models, overrides)
    assert merged == 1 and "zhipu/glm-x" in models

    snapshot = gen.build_snapshot(raw, "test", overrides)
    assert snapshot["schema_version"] == 1 and snapshot["model_count"] == len(snapshot["models"])


def test_committed_snapshot_fresh_drift() -> None:
    """drift CI 报警: 仓库内快照必须存在、新鲜 (≤60 天)、规模达标、关键模型在录。

    快照过期 → CI 每周刷新 workflow 失效, 本测试失败即报警。
    """
    assert SNAPSHOT_PATH.is_file(), "模型能力快照未入库 (scripts/gen_model_capabilities.py)"
    snap = CapabilitySnapshot.load(SNAPSHOT_PATH)
    assert len(snap) >= 1000, f"快照规模异常: {len(snap)} 模型"
    assert snap.fresh(60), f"快照过期: generated_at={snap.generated_at}"
    cap = snap.get("openai", "gpt-4o-mini")
    assert cap is not None and cap.supports_tools is True


# ── ③ category 路由 ──────────────────────────────────────────


def _llm_descriptor(pid: str, model: str, *, tools: bool, cost: str, latency: str) -> ModelDescriptor:
    return ModelDescriptor(
        provider_id=pid,
        model_id=model,
        modalities_in={"text"},
        modalities_out={"text"},
        operations={"chat"},
        supports_tools=tools,
        cost_tier=cost,
        latency_tier=latency,
    )


def _three_model_router() -> ModelRouter:
    catalog = ModelCatalog()
    catalog.register(_llm_descriptor("p_cheap", "cheap-1", tools=False, cost="low", latency="fast"))
    catalog.register(_llm_descriptor("p_mid", "mid-1", tools=True, cost="standard", latency="standard"))
    catalog.register(_llm_descriptor("p_pro", "pro-1", tools=True, cost="high", latency="slow"))
    return ModelRouter(catalog)


def test_profile_for_defaults_and_overrides() -> None:
    assert profile_for("qa") is not None
    assert profile_for("unknown_cat") is None
    qa = profile_for("qa", {"qa": {"cost_ceiling": "free"}})
    assert qa is not None and qa.cost_ceiling == "free" and qa.latency_target == "fast"


def test_select_for_category_qa_prefers_cheap_fast() -> None:
    selection = select_for_category(_three_model_router(), "qa")
    assert selection is not None
    assert selection.descriptor.model_id == "cheap-1"  # fast+standard 上限下唯一候选


def test_select_for_category_tool_heavy_requires_tools() -> None:
    selection = select_for_category(_three_model_router(), "tool_heavy")
    assert selection is not None
    # cheap-1 无工具支持被能力过滤排除; standard 与 high 间按打分 (成本权重) 取 mid-1
    assert selection.descriptor.model_id == "mid-1"


def test_select_for_category_chat_cost_ceiling() -> None:
    selection = select_for_category(_three_model_router(), "chat")
    assert selection is not None
    assert selection.descriptor.cost_tier == "low"  # chat 上限 low 排除 standard/high


def test_router_requires_tools_excludes_unknown_capability() -> None:
    catalog = ModelCatalog()
    catalog.register(_llm_descriptor("p", "m-tools", tools=True, cost="standard", latency="standard"))
    unknown = _llm_descriptor("p", "m-unknown", tools=False, cost="low", latency="fast")
    catalog.register(unknown)
    router = ModelRouter(catalog)
    selection = router.select(operation="chat", requires_tools=True)
    assert selection is not None and selection.descriptor.model_id == "m-tools"
    # 健康过滤: 唯一工具候选不健康时无候选
    router.record_health("p", healthy=False)
    assert router.select(operation="chat", requires_tools=True) is None


# ── ProviderManager 注册表 + 健康上报 ────────────────────────


class _FakeLLM:
    def __init__(self, reply: str = "ok", exc: Exception | None = None) -> None:
        self.reply = reply
        self.exc = exc
        self.calls = 0

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return LLMResponse(content=self.reply, usage=TokenUsage(total_tokens=1))

    def get_model_name(self) -> str:
        return "fake-model"


class _RecordingRouter:
    def __init__(self) -> None:
        self.records: list[tuple[str, bool]] = []

    def record_health(self, provider_id: str, *, healthy: bool) -> None:
        self.records.append((provider_id, healthy))


def test_register_llm_registry_and_lookup() -> None:
    manager = ProviderManager({})
    provider = _FakeLLM()
    manager.register(provider, provider_id="openai", model_id="gpt-4o-mini")
    assert manager.llm_provider_for("openai", "gpt-4o-mini") is provider
    assert manager.llm_provider_for("openai", "other") is None
    # 缺省键 (向后兼容旧调用方)
    fallback = _FakeLLM()
    manager.register(fallback, fallback=True)
    assert manager.llm_provider_for("fallback", "fake-model") is fallback


def test_report_health_with_and_without_router() -> None:
    manager = ProviderManager({})
    provider = _FakeLLM()
    manager.register(provider, provider_id="openai", model_id="m")
    manager._report_health(provider, healthy=False)  # 无 router: 无操作不报错
    router = _RecordingRouter()
    manager.model_router = router
    manager._report_health(provider, healthy=False)
    manager._report_health(provider, healthy=True)
    assert router.records == [("openai", False), ("openai", True)]


@pytest.mark.asyncio
async def test_chat_with_retry_success_records_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    manager = ProviderManager({})
    router = _RecordingRouter()
    manager.model_router = router
    provider = _FakeLLM(reply="ok")
    manager.register(provider, provider_id="openai", model_id="m")
    response = await manager.chat_with_retry(provider, messages=[])
    assert response.content == "ok"
    assert router.records == [("openai", True)]


@pytest.mark.asyncio
async def test_chat_with_retry_final_failure_records_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    manager = ProviderManager({})
    router = _RecordingRouter()
    manager.model_router = router
    provider = _FakeLLM(exc=LLMError("boom", retriable=False))
    manager.register(provider, provider_id="openai", model_id="m")
    response = await manager.chat_with_retry(provider, messages=[])
    assert response.content  # 降级回复
    assert router.records == [("openai", False)]


@pytest.mark.asyncio
async def test_chat_with_retry_rate_limit_not_marked_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """限流 (429) 是配额暂竭非不可达, 不标 unhealthy (避免恢复期不必要拉长)。"""

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    manager = ProviderManager({})
    router = _RecordingRouter()
    manager.model_router = router
    provider = _FakeLLM(exc=RateLimitError("429"))
    manager.register(provider, provider_id="openai", model_id="m")
    await manager.chat_with_retry(provider, messages=[])
    assert ("openai", False) not in router.records


# ── 委派 runner category 选型 ────────────────────────────────


def _task(category: str) -> SubAgentTask:
    return SubAgentTask(
        task_id="t1",
        parent_agent_id="a1",
        session_id="s1",
        trace_id="t1",
        objective="o",
        context={"category": category},
    )


def _fake_instance(llm: Any, provider_manager: Any, services: dict[str, Any]) -> Any:
    return SimpleNamespace(
        loop=SimpleNamespace(llm=llm, provider_manager=provider_manager),
        services=ServiceContainer(services),
    )


def test_select_llm_no_category_keeps_parent() -> None:
    parent_llm = _FakeLLM()
    instance = _fake_instance(parent_llm, ProviderManager({}), {})
    assert _select_llm_for_task(instance, _task("")) is parent_llm


def test_select_llm_switches_on_category_hit() -> None:
    parent_llm = _FakeLLM()
    cheap = _FakeLLM()
    manager = ProviderManager({})
    manager.register(parent_llm, provider_id="p_mid", model_id="mid-1")
    manager.register(cheap, provider_id="p_cheap", model_id="cheap-1")
    catalog = ModelCatalog()
    catalog.register(_llm_descriptor("p_mid", "mid-1", tools=True, cost="standard", latency="standard"))
    catalog.register(_llm_descriptor("p_cheap", "cheap-1", tools=False, cost="low", latency="fast"))
    router = ModelRouter(catalog)
    instance = _fake_instance(
        parent_llm, manager, {"model_router": router, "global_config": {}}
    )
    # chat 类命中 cheap (low+fast), 切换模型
    assert _select_llm_for_task(instance, _task("chat")) is cheap
    # tool_heavy 命中父模型本身 → 不切换 (同一实例)
    assert _select_llm_for_task(instance, _task("tool_heavy")) is parent_llm


def test_select_llm_fallback_when_no_candidate() -> None:
    parent_llm = _FakeLLM()
    manager = ProviderManager({})
    manager.register(parent_llm, provider_id="p_mid", model_id="mid-1")
    catalog = ModelCatalog()  # 空目录 → 任何 category 无候选
    router = ModelRouter(catalog)
    instance = _fake_instance(
        parent_llm, manager, {"model_router": router, "global_config": {}}
    )
    assert _select_llm_for_task(instance, _task("qa")) is parent_llm
    # 无 model_router → 回落
    instance2 = _fake_instance(parent_llm, manager, {"global_config": {}})
    assert _select_llm_for_task(instance2, _task("qa")) is parent_llm
