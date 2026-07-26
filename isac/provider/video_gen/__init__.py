"""视频生成 Provider (O5 企业化/多模态补齐)。

[框架已搭建 / scaffolding] OpenAICompatVideoGenProvider 骨架就位 (实现
VideoGenerationProvider ABC)。真实 API 接入见 DEVELOPMENT_PLAN.md §四 O5;
端点开工前需二次确认, 故不自动注册到 ModelRouter, 零行为变化。
"""

from __future__ import annotations

from isac.provider.video_gen.openai_compat import OpenAICompatVideoGenProvider

__all__ = ["OpenAICompatVideoGenProvider"]
