"""平台适配器模板 (O4 平台扩展)。

[框架已搭建 / scaffolding] TemplateAdapter 文档化骨架, 作为新增 IM 平台
(微信/Slack/飞书…) 的可复制起点。**不自动注册**; 复制到 adapters/<platform>/ 后
按 DEVELOP.md 3.3 实现。既有 channel/base.py PlatformAdapter ABC 不动。
"""

from __future__ import annotations

from isac.channel.adapters.template.adapter import TemplateAdapter

__all__ = ["TemplateAdapter"]
