"""J1 价格目录与成本快照 (SPECIFICATION.md 2.3)。

成本用"调用时价格快照"计算, 不写死在 Provider 代码里; 价格未知时保存用量但
``estimated_cost=None``; 历史记录不因后续调价重算。

骨架状态: 内存价目表 + lookup / estimate_cost 接口就位; 真实价目加载 (配置/远程)、
多档计价 (input/output/cache/audio/非 Token 单位) 留待 J1 实现节点。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isac.observability.usage.models import ModelUsageEvent


@dataclass
class PriceSnapshot:
    """某模型在某价格版本下的单价快照 (Decimal 字符串, 避免浮点误差)。

    cache_read/cache_write/audio_{input,output}_price_per_unit 为 None 时回退到
    对应的基础 input/output 价, 向后兼容未配置分档价的旧快照。
    """

    provider: str
    model: str
    modality: str
    pricing_version: str
    input_price_per_unit: str = "0"
    output_price_per_unit: str = "0"
    cache_read_price_per_unit: str | None = None
    cache_write_price_per_unit: str | None = None
    audio_input_price_per_unit: str | None = None
    audio_output_price_per_unit: str | None = None
    unit_name: str = "token"
    currency: str = "USD"


class PricingCatalog:
    """价格目录: 按 (provider, model, modality) 查快照并估算成本。"""

    def __init__(self, snapshots: list[PriceSnapshot] | None = None, version: str = "") -> None:
        self.version = version
        self._by_key: dict[tuple[str, str, str], PriceSnapshot] = {}
        for snapshot in snapshots or []:
            self.register(snapshot)

    def register(self, snapshot: PriceSnapshot) -> None:
        """登记一条价格快照。"""
        self._by_key[(snapshot.provider, snapshot.model, snapshot.modality)] = snapshot

    @classmethod
    def load(cls, path: str | object) -> PricingCatalog:
        """R1-④: 从 jsonc 加载价目表 (provider/model/modality → PriceSnapshot)。

        文件不存在或解析失败返回空 catalog (不 raise, estimated_cost 恒 None,
        向后兼容)。jsonc 用 json5 解析 (降级 json)。
        """
        from pathlib import Path

        try:
            import json5

            _loads = json5.loads
        except ImportError:  # pragma: no cover
            import json

            _loads = json.loads
        p = Path(path)  # type: ignore[arg-type]
        if not p.exists():
            return cls()
        try:
            data = _loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("价目表加载失败, 用空目录: %s (%s)", p, exc)
            return cls()
        snapshots: list[PriceSnapshot] = []
        version = str(data.get("version", "")) if isinstance(data, dict) else ""
        for entry in (data.get("snapshots", []) if isinstance(data, dict) else []):
            if not isinstance(entry, dict):
                continue
            snapshots.append(PriceSnapshot(
                provider=str(entry.get("provider", "")),
                model=str(entry.get("model", "")),
                modality=str(entry.get("modality", "text")),
                pricing_version=str(entry.get("pricing_version", version or "v1")),
                input_price_per_unit=str(entry.get("input_price_per_unit", "0")),
                output_price_per_unit=str(entry.get("output_price_per_unit", "0")),
                cache_read_price_per_unit=entry.get("cache_read_price_per_unit"),
                cache_write_price_per_unit=entry.get("cache_write_price_per_unit"),
                audio_input_price_per_unit=entry.get("audio_input_price_per_unit"),
                audio_output_price_per_unit=entry.get("audio_output_price_per_unit"),
                unit_name=str(entry.get("unit_name", "token")),
                currency=str(entry.get("currency", "USD")),
            ))
        return cls(snapshots, version=version)

    def lookup(self, provider: str, model: str, modality: str) -> PriceSnapshot | None:
        """查询价格快照; 未登记返回 None。"""
        return self._by_key.get((provider, model, modality))

    def estimate_cost(self, event: ModelUsageEvent) -> str | None:
        """按调用时价格快照估算成本 (Decimal 字符串)。未知价格返回 None。

        text modality (token 单位) 用分档公式:
          cache_read_tokens/audio_input_tokens 是 prompt_tokens 的子集,
          audio_output_tokens 是 completion_tokens 的子集 (OpenAI 语义):
          从基础档中减去后单独按 (专属价或回退到基础价) 计价, 避免重复计数。
          reasoning_tokens 同样是 completion_tokens 子集, 但 OpenAI 按输出价
          整体计费, 故只做可观测拆分, 不参与计价公式。cache_write_tokens
          当前没有 Provider 产生非 0 值, 不是任何字段的子集, 按额外加项计入。

        非文本 modality (image/audio_stt/audio_tts/embed/rerank/video 等):
          按 input_units * input_price + output_units * output_price 计算,
          unit_name 由 PriceSnapshot 配置 (image/second/vector/candidate)。
        """
        snapshot = self.lookup(event.provider, event.model, event.modality)
        if snapshot is None:
            return None
        # 非文本 modality: 按 input_units/output_units 计价
        if event.modality != "text":
            input_price = Decimal(snapshot.input_price_per_unit)
            output_price = Decimal(snapshot.output_price_per_unit)
            # Fix-27: input_units/output_units 是 float 字段 (图片张数/音频秒数等),
            # 直接 Decimal(float) 会保留二进制浮点的原始误差 (如 Decimal(0.1) 不是
            # 精确的 0.1), 与本模块文档"Decimal 避免浮点误差"的意图相悖。经
            # str() 先转成十进制文本表示再构造 Decimal, 才是精确值。
            total = (
                Decimal(str(event.input_units)) * input_price
                + Decimal(str(event.output_units)) * output_price
            )
            return str(total)
        # text modality: 走分档 token 公式 (含 cache/audio 明细)
        usage = event.usage
        input_price = Decimal(snapshot.input_price_per_unit)
        output_price = Decimal(snapshot.output_price_per_unit)
        cache_read_price = Decimal(snapshot.cache_read_price_per_unit or snapshot.input_price_per_unit)
        cache_write_price = Decimal(snapshot.cache_write_price_per_unit or snapshot.input_price_per_unit)
        audio_input_price = Decimal(snapshot.audio_input_price_per_unit or snapshot.input_price_per_unit)
        audio_output_price = Decimal(snapshot.audio_output_price_per_unit or snapshot.output_price_per_unit)

        base_prompt_tokens = max(0, usage.prompt_tokens - usage.cache_read_tokens - usage.audio_input_tokens)
        base_completion_tokens = max(0, usage.completion_tokens - usage.audio_output_tokens)

        total = (
            Decimal(base_prompt_tokens) * input_price
            + Decimal(usage.cache_read_tokens) * cache_read_price
            + Decimal(usage.audio_input_tokens) * audio_input_price
            + Decimal(base_completion_tokens) * output_price
            + Decimal(usage.audio_output_tokens) * audio_output_price
            + Decimal(usage.cache_write_tokens) * cache_write_price
        )
        return str(total)
