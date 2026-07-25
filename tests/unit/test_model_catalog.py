"""J2 多模态 Provider 与能力选择框架骨架测试。

覆盖能力目录、路由过滤 (operation / 模态 / 授权)、能力注入器与制品引用。真实模型调用、
成本/延迟打分、制品落地属实现节点范畴, 不在此覆盖。
"""

from __future__ import annotations

from isac.agent.tools.base import ToolContext, ToolPermission
from isac.agent.tools.media import GenerateImageTool
from isac.artifacts.models import ArtifactRef
from isac.artifacts.store import ArtifactStore
from isac.core.types import InjectionContext
from isac.provider.catalog import ModelCatalog, ModelDescriptor
from isac.provider.router import ModelRouter


def _descriptor(operation: str = "image_gen", **kw) -> ModelDescriptor:
    base = dict(
        provider_id="P",
        model_id=f"m-{operation}",
        modalities_in={"text"},
        modalities_out={"image"},
        operations={operation},
    )
    base.update(kw)
    return ModelDescriptor(**base)  # type: ignore[arg-type]


def test_catalog_register_get_list() -> None:
    catalog = ModelCatalog()
    desc = _descriptor()
    catalog.register(desc)
    assert catalog.get("P", "m-image_gen") is desc
    assert catalog.get("P", "missing") is None
    assert catalog.list_all() == [desc]


def test_catalog_find_by_operation() -> None:
    catalog = ModelCatalog()
    catalog.register(_descriptor("image_gen"))
    catalog.register(_descriptor("stt", modalities_in={"audio"}, modalities_out={"text"}))
    assert len(catalog.find_by_operation("image_gen")) == 1
    assert catalog.find_by_operation("video_gen") == []


def test_router_selects_matching_model() -> None:
    catalog = ModelCatalog()
    catalog.register(_descriptor("image_gen"))
    router = ModelRouter(catalog)
    selection = router.select(operation="image_gen", modalities_out={"image"})
    assert selection is not None
    assert selection.descriptor.model_id == "m-image_gen"
    assert "image_gen" in selection.reason


def test_router_returns_none_without_candidate() -> None:
    router = ModelRouter(ModelCatalog())
    assert router.select(operation="image_gen") is None


def test_router_respects_authorization() -> None:
    catalog = ModelCatalog()
    catalog.register(_descriptor("image_gen"))
    router = ModelRouter(catalog)
    # operation 未在授权集合内 → 直接无候选
    assert router.select(operation="image_gen", allowed_operations={"chat"}) is None
    assert router.select(operation="image_gen", allowed_operations={"image_gen"}) is not None


def test_router_modality_filter_excludes_mismatch() -> None:
    catalog = ModelCatalog()
    catalog.register(_descriptor("image_gen", modalities_out={"image"}))
    router = ModelRouter(catalog)
    # 需要 video 输出但候选只产 image → 无候选
    assert router.select(operation="image_gen", modalities_out={"video"}) is None


def test_artifact_store_make_ref() -> None:
    store = ArtifactStore("/tmp/isac-artifacts")
    ref = store.make_ref("art_1", kind="image", mime_type="image/png", uri="file:///x.png")
    assert isinstance(ref, ArtifactRef)
    assert ref.artifact_id == "art_1"
    assert ref.kind == "image"


async def test_model_capabilities_injector_empty_by_default() -> None:
    from isac.agent.injectors.model_capabilities import ModelCapabilitiesInjector

    injector = ModelCapabilitiesInjector([])
    ctx = InjectionContext(session=object(), user_profile=None, current_message=object())  # type: ignore[arg-type]
    assert await injector.build(ctx) == ""


async def test_model_capabilities_injector_lists_authorized() -> None:
    from isac.agent.injectors.model_capabilities import ModelCapabilitiesInjector

    injector = ModelCapabilitiesInjector(["generate_image", "bogus"])
    ctx = InjectionContext(session=object(), user_profile=None, current_message=object())  # type: ignore[arg-type]
    text = await injector.build(ctx)
    assert "生成图片" in text
    # 未知能力被忽略
    assert "bogus" not in text


async def test_media_tool_stub_returns_friendly_error_without_backend() -> None:
    tool = GenerateImageTool()
    ctx = ToolContext(args={"prompt": "一只猫"}, agent_context=object(), services={})  # type: ignore[arg-type]
    result = await tool.execute(ctx)
    assert result.is_error is True


def test_media_tools_default_denied() -> None:
    permission = ToolPermission()
    for name in ("generate_image", "generate_video", "transcribe_audio", "synthesize_speech", "understand_video"):
        assert permission.check(name) == "deny"
