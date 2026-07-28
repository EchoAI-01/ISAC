"""J2 阶段 1: ArtifactStore 本地 FS + TTL 单元测试。

覆盖:
- put bytes → get 还原
- sha256 决定性 (同内容同 ID, 路径 data/artifacts/<sha[:2]>/<sha>.bin)
- expires_at 过期后 get 返回 None
- sweep_expired() 删文件 + 元数据行
- start_ttl_sweep / stop 周期任务生命周期 (不抛异常)
- 默认 ttl_days 应用
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from isac.artifacts.models import ArtifactRef
from isac.artifacts.store import ArtifactStore


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(str(tmp_path / "artifacts"), ttl_days=7)


@pytest.mark.asyncio
async def test_concurrent_put_same_content_does_not_raise(tmp_path: Path) -> None:
    """并发 put 字节级相同内容: 历史上用固定 tmp 文件名, 一方抢 rename 走另一方的
    tmp 后另一方的 replace 抛 FileNotFoundError; 现在每次唯一 tmp + 幂等兜底。
    """
    store = ArtifactStore(str(tmp_path / "artifacts"), ttl_days=7)
    data = b"concurrent-duplicate-content"

    async def _put_once() -> ArtifactRef:
        return await store.put(data, kind="image", mime_type="image/png")

    results = await asyncio.gather(*[_put_once() for _ in range(8)])

    artifact_ids = {ref.artifact_id for ref in results}
    assert len(artifact_ids) == 1
    for ref in results:
        assert ref.size_bytes == len(data)


@pytest.mark.asyncio
async def test_put_and_get_roundtrip(store: ArtifactStore) -> None:
    data = b"\x89PNG\r\n\x1a\n" + b"fake image content"
    ref = await store.put(data, kind="image", mime_type="image/png")
    assert isinstance(ref, ArtifactRef)
    assert ref.kind == "image"
    assert ref.mime_type == "image/png"
    assert ref.size_bytes == len(data)
    assert len(ref.artifact_id) == 64  # sha256 hex
    got = await store.get(ref.artifact_id)
    assert got == data


@pytest.mark.asyncio
async def test_put_sha256_deterministic_and_path_layout(store: ArtifactStore) -> None:
    data = b"same content for sha check"
    ref1 = await store.put(data, kind="image")
    ref2 = await store.put(data, kind="image")
    assert ref1.artifact_id == ref2.artifact_id  # 同内容 → 同 ID
    file_path = Path(store.root_dir) / ref1.artifact_id[:2] / f"{ref1.artifact_id}.bin"
    assert file_path.exists()
    assert file_path.stat().st_size == len(data)


@pytest.mark.asyncio
async def test_get_unknown_returns_none(store: ArtifactStore) -> None:
    assert await store.get("nonexistent_id") is None


@pytest.mark.asyncio
async def test_get_returns_none_after_expiry(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"), ttl_days=7)
    data = b"expiring soon"
    ref = await store.put(data, kind="image", expires_at=int(time.time()) + 1)
    assert await store.get(ref.artifact_id) is not None
    await asyncio.sleep(2.0)
    assert await store.get(ref.artifact_id) is None


@pytest.mark.asyncio
async def test_sweep_expired_deletes_files_and_metadata(store: ArtifactStore) -> None:
    data = b"to be swept"
    ref = await store.put(data, kind="image", expires_at=int(time.time()) - 10)
    file_path = Path(store.root_dir) / ref.artifact_id[:2] / f"{ref.artifact_id}.bin"
    assert file_path.exists()
    await store.sweep_expired()
    assert not file_path.exists()
    assert await store.get(ref.artifact_id) is None


@pytest.mark.asyncio
async def test_sweep_keeps_non_expired(store: ArtifactStore) -> None:
    data = b"keep me"
    ref = await store.put(data, kind="image", expires_at=int(time.time()) + 3600)
    await store.sweep_expired()
    assert await store.get(ref.artifact_id) == data


@pytest.mark.asyncio
async def test_default_ttl_applied_when_unspecified(tmp_path: Path) -> None:
    store = ArtifactStore(str(tmp_path / "artifacts"), ttl_days=7)
    data = b"default ttl"
    ref = await store.put(data, kind="image")
    now = int(time.time())
    assert ref.expires_at > now + 3600 * 24 * 6  # 至少 6 天后
    assert ref.expires_at < now + 3600 * 24 * 8  # 不超过 8 天


@pytest.mark.asyncio
async def test_put_explicit_no_expiry_persists_indefinitely(store: ArtifactStore) -> None:
    data = b"never expire"
    ref = await store.put(data, kind="image", expires_at=0)
    assert ref.expires_at == 0
    await store.sweep_expired()
    assert await store.get(ref.artifact_id) == data


@pytest.mark.asyncio
async def test_make_ref_for_existing(store: ArtifactStore) -> None:
    data = b"hello audio"
    ref = await store.put(data, kind="audio", mime_type="audio/wav")
    ref2 = store.make_ref(ref.artifact_id, kind="audio", mime_type="audio/wav")
    assert ref2.artifact_id == ref.artifact_id
    assert ref2.kind == "audio"
    assert ref2.mime_type == "audio/wav"


@pytest.mark.asyncio
async def test_ttl_loop_lifecycle(store: ArtifactStore) -> None:
    await store.start_ttl_sweep(interval_seconds=0.01)
    assert store._ttl_task is not None
    await asyncio.sleep(0.05)  # 让循环跑几次
    await store.stop()
    assert store._ttl_task is None or store._ttl_task.done()


@pytest.mark.asyncio
async def test_put_empty_data_still_works(store: ArtifactStore) -> None:
    ref = await store.put(b"", kind="file", mime_type="application/octet-stream")
    assert ref.size_bytes == 0
    got = await store.get(ref.artifact_id)
    assert got == b""


@pytest.mark.asyncio
async def test_put_metadata_persisted(store: ArtifactStore) -> None:
    data = b"with metadata"
    ref = await store.put(data, kind="image", metadata={"prompt": "a cat", "n": 1})
    assert ref.metadata == {"prompt": "a cat", "n": 1}
    # 再读回来 make_ref 不带 metadata, 但 DB 行已存, 后续可按 artifact_id 查元数据
    file_path = Path(store.root_dir) / ref.artifact_id[:2] / f"{ref.artifact_id}.bin"
    assert file_path.exists()
