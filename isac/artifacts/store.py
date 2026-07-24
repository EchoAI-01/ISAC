"""J2 制品存储 (SPECIFICATION.md 2.4)。

生成结果写入 ArtifactStore, 返回 ``ArtifactRef``, 再由 Channel Adapter 按平台能力
发送或降级为受控下载链接。二进制内容不得直接塞入对话历史、日志或记忆。

骨架状态: put/get/make_ref 接口就位; 真实存储后端 (本地目录 / 对象存储 / 签名 URL /
TTL 清理) 留待 J2 实现节点。
"""

from __future__ import annotations

from isac.artifacts.models import ArtifactRef


class ArtifactStore:
    """多模态制品存储。"""

    def __init__(self, root_dir: str) -> None:
        self.root_dir = root_dir

    async def put(
        self,
        data: bytes,
        *,
        kind: str,
        mime_type: str = "",
        metadata: dict | None = None,
    ) -> ArtifactRef:
        """保存二进制制品并返回受控引用。

        TODO(J2): 写入 root_dir / 对象存储, 生成受控访问 URI 与 TTL, 记录大小/时长。
        """
        raise NotImplementedError("ArtifactStore.put 待 J2 实现节点落地")

    async def get(self, artifact_id: str) -> bytes | None:
        """按 artifact_id 读取二进制内容; 不存在返回 None。"""
        raise NotImplementedError("ArtifactStore.get 待 J2 实现节点落地")

    def make_ref(
        self,
        artifact_id: str,
        *,
        kind: str,
        mime_type: str = "",
        uri: str = "",
    ) -> ArtifactRef:
        """为已存在制品构造一个受控引用 (不落盘)。"""
        return ArtifactRef(artifact_id=artifact_id, kind=kind, mime_type=mime_type, uri=uri)
