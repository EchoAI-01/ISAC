"""PromptInjector 兼容入口。

原实现已下沉到 `isac.core.injector`，此处保留 re-export 以免破坏已有导入。
新注入器建议直接从 `isac.core.injector` 继承。
"""

from __future__ import annotations

from isac.core.injector import PromptInjector

__all__ = ["PromptInjector"]
