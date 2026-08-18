"""query_person_profile 工具: 查询人物画像 (只读)。"""

from __future__ import annotations

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class QueryPersonProfileTool(Tool):
    @property
    def name(self) -> str:
        return "query_person_profile"

    @property
    def description(self) -> str:
        return "查询某个用户的画像信息 (只读)"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {"user_name": {"type": "string", "description": "用户名"}},
            "required": ["user_name"],
        }

    async def execute(self, context: ToolContext) -> ToolResult:
        """查询人物画像。"""
        memory = context.services.get("memory")
        metadata = getattr(memory, "metadata", None) if memory is not None else None
        if metadata is None or not hasattr(metadata, "get_person_profile"):
            return ToolResult(content="未启用人物画像存储，无法查询画像。", is_error=True)

        raw_user_name = str(context.args.get("user_name", "")).strip()
        # U4: person_id 口径与写侧一致 —— 工具参数优先, 其次归一 master_id
        # (user_profile.user_id), 最后平台 session.user_id。agent 键统一用
        # pipeline.namespace (租户前缀/自定义 namespace 下与写侧同键)。
        profile = getattr(context.agent_context, "user_profile", None)
        person_id = (
            raw_user_name
            or str(getattr(profile, "user_id", "") or "")
            or getattr(context.agent_context.session, "user_id", "")
        )
        if not person_id:
            return ToolResult(content="query_person_profile 缺少用户标识。", is_error=True)
        agent_key = str(
            getattr(memory, "namespace", "") or getattr(context.agent_context.session, "agent_id", "")
        )

        try:
            profile_row = await metadata.get_person_profile(agent_key, person_id)
        except Exception as exc:
            return ToolResult(content=f"人物画像查询失败：{exc}", is_error=True)

        if not profile_row:
            return ToolResult(content=f"未找到 {person_id} 的人物画像。")
        return ToolResult(content=self._format_profile(profile_row))

    @staticmethod
    def _format_profile(profile: dict) -> str:
        name = profile.get("name") or profile.get("person_id") or "未知用户"
        profile_text = profile.get("profile_text") or "暂无画像摘要"
        relationship_depth = profile.get("relationship_depth", 0.0)
        return "\n".join(
            [
                "【人物画像】",
                f"用户: {name}",
                f"关系深度: {float(relationship_depth):.2f}",
                f"画像: {profile_text}",
            ]
        )
