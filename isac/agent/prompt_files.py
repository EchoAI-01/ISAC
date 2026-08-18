"""U7 prompt 文件化: 人格/规则写 markdown 文件, SystemPromptBuilder 从文件装配。

约定 (SPECIFICATION.md 1.6 扩展):
- 每个 Agent 的 prompt 文件放在 ``data/agents/<agent_id>/prompts/*.md``;
- 文件 = 一个 prompt 块。frontmatter (``---`` 包围) 声明元数据:
    - ``family``: prompt 族 (persona / rules / 自定义), 同族文件互为**变体**;
    - ``variant``: 变体键 (默认 ``default``; 模型族变体如 ``gpt`` / ``claude``);
    - ``priority``: int, 注入优先级 (缺省 50; persona 建议 100);
    - ``enabled``: bool, 缺省 true。
- **改人格 = 改文件**: persona 族存在时替代 config.persona.description 的身份注入;
  **新增一个模型族 = 加一个文件** (variant 键 = 模型族名, 零代码改动)。

frontmatter 解析为无第三方依赖的子集解析器 (key: value; 值支持字符串/整数/
布尔/行内列表), 与仓库"不新增依赖"纪律一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 模型名 → 模型族映射前缀 (变体选择用; 未命中回落 default 变体)。
# 新增模型族不需要改这里 —— variant 选择未命中时回落 default 变体;
# 也可在 config.llm.model_family 显式声明族名。
_MODEL_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("gpt-", "gpt"),
    ("o1", "openai_reasoning"),
    ("o3", "openai_reasoning"),
    ("o4", "openai_reasoning"),
    ("chatgpt-", "gpt"),
    ("claude-", "claude"),
    ("gemini-", "gemini"),
    ("qwen", "qwen"),
    ("deepseek-", "deepseek"),
    ("grok-", "grok"),
    ("llama-", "llama"),
    ("glm-", "glm"),
    ("kimi", "kimi"),
    ("minimax-", "minimax"),
    ("doubao-", "doubao"),
    ("ernie-", "ernie"),
)


def model_family_of(model_name: str, override: str = "") -> str:
    """从模型名推断模型族 (config.llm.model_family 覆盖优先; 未知 → "default")。"""
    override = override.strip()
    if override:
        return override
    lowered = (model_name or "").strip().lower()
    for prefix, family in _MODEL_FAMILY_PREFIXES:
        if lowered.startswith(prefix):
            return family
    return "default"


def _parse_scalar(raw: str) -> Any:
    """frontmatter 标量解析: bool / int / 行内列表 / 去引号字符串。"""
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1]
        return [_parse_scalar(item) for item in inner.split(",") if item.strip()]
    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析 ``---`` 包围的 frontmatter, 返回 (元数据, 正文)。

    无 frontmatter 时返回 ({}, 原文)。仅支持 ``key: value`` 单行子集
    (不引第三方 YAML 依赖); 解析不了的行忽略并告警。
    """
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    end_index = -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index < 0:
        return {}, text  # 未闭合的 frontmatter 视为普通正文
    meta: dict[str, Any] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            logger.debug("prompt frontmatter 行无冒号, 忽略", line=stripped)
            continue
        key, _, value = stripped.partition(":")
        meta[key.strip()] = _parse_scalar(value)
    body = "\n".join(lines[end_index + 1 :]).strip("\n")
    return meta, body


@dataclass
class PromptDoc:
    """一个 prompt 文件 (family + variant 定位, body 为注入内容)。"""

    family: str
    variant: str = "default"
    priority: int = 50
    enabled: bool = True
    body: str = ""
    path: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def load_prompt_dir(directory: str | Path) -> dict[str, list[PromptDoc]]:
    """加载目录下全部 ``*.md`` prompt 文件, 按 family 分组。

    文件缺失/解析失败跳过并告警 (不阻塞 Agent 启动)。返回空 dict = 无 prompt 文件
    (调用方走既有 config 路径, 零行为变化)。
    """
    root = Path(directory)
    if not root.is_dir():
        return {}
    grouped: dict[str, list[PromptDoc]] = {}
    for file_path in sorted(root.glob("*.md")):
        try:
            meta, body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("prompt 文件读取失败, 跳过", path=str(file_path), error=str(exc))
            continue
        family = str(meta.get("family") or "").strip()
        if not family or not body.strip():
            logger.debug("prompt 文件缺 family 或正文为空, 跳过", path=str(file_path))
            continue
        doc = PromptDoc(
            family=family,
            variant=str(meta.get("variant") or "default").strip() or "default",
            priority=int(meta.get("priority", 50)) if isinstance(meta.get("priority", 50), int) else 50,
            enabled=bool(meta.get("enabled", True)),
            body=body,
            path=str(file_path),
            meta=meta,
        )
        grouped.setdefault(family, []).append(doc)
    for docs in grouped.values():
        docs.sort(key=lambda d: d.variant == "default", reverse=True)  # default 变体在前
    return grouped


class FilePromptInjector(PromptInjector):
    """prompt 文件族注入器: 同族多变体按当前模型族选择, 未命中回落 default。"""

    def __init__(
        self,
        family: str,
        docs: list[PromptDoc],
        family_resolver: Any = None,
        priority: int | None = None,
    ) -> None:
        self._family = family
        self._docs = list(docs)
        # family_resolver: () -> str, 返回当前模型族名 (缺省/失败 → "default")
        self._family_resolver = family_resolver
        self._priority = priority if priority is not None else max((d.priority for d in docs), default=50)

    @property
    def key(self) -> str:
        return f"file_prompt:{self._family}"

    @property
    def priority(self) -> int:
        return self._priority

    @property
    def tokens_estimate(self) -> int:
        return max((len(d.body) for d in self._docs), default=0) // 2

    def select_doc(self) -> PromptDoc | None:
        """按当前模型族选变体: 精确匹配 → default → 首个 enabled。"""
        enabled = [d for d in self._docs if d.enabled]
        if not enabled:
            return None
        family = "default"
        if self._family_resolver is not None:
            try:
                family = str(self._family_resolver() or "default")
            except Exception:  # noqa: BLE001 解析器故障回落 default
                family = "default"
        for doc in enabled:
            if doc.variant == family:
                return doc
        for doc in enabled:
            if doc.variant == "default":
                return doc
        return enabled[0]

    async def build(self, context: InjectionContext) -> str:
        doc = self.select_doc()
        return doc.body if doc is not None else ""
