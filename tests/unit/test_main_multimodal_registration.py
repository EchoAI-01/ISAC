"""J2 阶段 8: main.py 多模态 Provider 注册循环测试。

覆盖:
- 一条 image_gen 配置 → catalog 有 descriptor + provider_manager 可查到实例
- 多 kind (image_gen + stt + tts + embed + vision) 并存
- 缺 api_key/base_url/model → 跳过 + 不注册
- 未知 kind → 跳过
- cost_tier/latency_tier 从 config 取并写入 ModelDescriptor
"""

from __future__ import annotations

from isac.artifacts.store import ArtifactStore
from isac.main import register_multimodal_providers
from isac.provider.catalog import ModelCatalog
from isac.provider.image_gen.openai_compat import OpenAICompatImageGenProvider
from isac.provider.llm.openai_compat import OpenAICompatProvider
from isac.provider.manager import ProviderManager
from isac.provider.stt_tts.openai_compat import (
    OpenAICompatSTTProvider,
    OpenAICompatTTSProvider,
)


def _build_services() -> tuple[ProviderManager, ModelCatalog, ArtifactStore]:
    artifact_store = ArtifactStore("/tmp/test_artifacts_j2")  # 不会真写入, 仅传引用
    return ProviderManager({}), ModelCatalog(), artifact_store


def test_register_image_gen_provider() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {
            "kind": "image_gen", "provider": "openai", "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1", "model": "dall-e-3",
            "cost_tier": "low", "latency_tier": "standard",
        }
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    # catalog 有 descriptor
    descriptors = catalog.find_by_operation("image_gen")
    assert len(descriptors) == 1
    d = descriptors[0]
    assert d.provider_id == "openai"
    assert d.model_id == "dall-e-3"
    assert d.modalities_in == {"text"}
    assert d.modalities_out == {"image"}
    assert d.cost_tier == "low"
    assert d.latency_tier == "standard"
    # provider_manager 可查到实例
    provider = pm.multimodal_provider("openai", "dall-e-3")
    assert provider is not None
    assert isinstance(provider, OpenAICompatImageGenProvider)


def test_register_multiple_kinds() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {"kind": "image_gen", "provider": "openai", "api_key": "k", "base_url": "u", "model": "dall-e-3"},
        {"kind": "stt", "provider": "openai", "api_key": "k", "base_url": "u", "model": "whisper-1"},
        {"kind": "tts", "provider": "openai", "api_key": "k", "base_url": "u", "model": "tts-1"},
        {"kind": "embed", "provider": "openai", "api_key": "k", "base_url": "u", "model": "text-embedding-3-small"},
        {"kind": "vision", "provider": "openai", "api_key": "k", "base_url": "u", "model": "gpt-4o"},
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    assert len(catalog.list_all()) == 5
    assert pm.multimodal_provider("openai", "dall-e-3") is not None
    assert pm.multimodal_provider("openai", "whisper-1") is not None
    assert pm.multimodal_provider("openai", "tts-1") is not None
    assert pm.multimodal_provider("openai", "text-embedding-3-small") is not None
    assert pm.multimodal_provider("openai", "gpt-4o") is not None
    # 类型校验
    assert isinstance(pm.multimodal_provider("openai", "whisper-1"), OpenAICompatSTTProvider)
    assert isinstance(pm.multimodal_provider("openai", "tts-1"), OpenAICompatTTSProvider)
    assert isinstance(pm.multimodal_provider("openai", "gpt-4o"), OpenAICompatProvider)


def test_register_skips_missing_api_key() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {"kind": "image_gen", "provider": "openai", "base_url": "u", "model": "dall-e-3"},
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    assert catalog.list_all() == []
    assert pm.multimodal_provider("openai", "dall-e-3") is None


def test_register_skips_missing_model() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {"kind": "image_gen", "provider": "openai", "api_key": "k", "base_url": "u"},
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    assert catalog.list_all() == []


def test_register_skips_unknown_kind() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {"kind": "unknown_kind", "provider": "openai", "api_key": "k", "model": "x"},
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    assert catalog.list_all() == []


def test_register_skips_empty_list() -> None:
    pm, catalog, store = _build_services()
    register_multimodal_providers(pm, catalog, store, [])
    assert catalog.list_all() == []


def test_register_skips_none_list() -> None:
    pm, catalog, store = _build_services()
    register_multimodal_providers(pm, catalog, store, None)  # type: ignore[arg-type]
    assert catalog.list_all() == []


def test_register_default_cost_latency_tiers() -> None:
    pm, catalog, store = _build_services()
    mm_list = [
        {"kind": "image_gen", "provider": "openai", "api_key": "k", "model": "dall-e-3"},
    ]
    register_multimodal_providers(pm, catalog, store, mm_list)
    d = catalog.find_by_operation("image_gen")[0]
    assert d.cost_tier == "standard"  # 默认
    assert d.latency_tier == "standard"  # 默认
