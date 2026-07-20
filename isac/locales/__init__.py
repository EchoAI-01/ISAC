"""多语言支持 (i18n)。

ADR-006: 注入器只引用 key，通过 load_text() 获取本地化文本。
新增语言: 复制 zh_CN.py 为新语言文件，保持 key 一致。
"""

from __future__ import annotations

from isac.locales import en_US, zh_CN
from isac.utils.logger import get_logger

logger = get_logger(__name__)

_LOCALES: dict[str, dict[str, str]] = {
    "zh_CN": zh_CN.TEXTS,
    "en_US": en_US.TEXTS,
}

DEFAULT_LOCALE = "zh_CN"


def load_text(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """按 key 获取本地化文本。

    Args:
        key: 点分层级 key，如 "attention_drift.subtle"
        locale: 语言标识，默认 zh_CN；缺失时回退到默认语言

    Returns:
        本地化文本；key 不存在时返回 key 本身并记录警告。
    """
    texts = _LOCALES.get(locale, _LOCALES[DEFAULT_LOCALE])
    text = texts.get(key)
    if text is None:
        text = _LOCALES[DEFAULT_LOCALE].get(key)
    if text is None:
        logger.warning("缺失 i18n key", key=key, locale=locale)
        return key
    return text


def register_locale(locale: str, texts: dict[str, str]) -> None:
    """注册新的语言包（插件可用）。"""
    _LOCALES[locale] = texts
