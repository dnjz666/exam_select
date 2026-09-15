"""六省市规则包注册表（批次级 / ADR-006）。

本模块是规则包的唯一入口：`get_rule(province)` / `all_rules()` / `batch_by_code()`。
纯数据 + 纯函数，禁止 IO（core/ 铁律）。
"""

from __future__ import annotations

from app.core.models import BatchRule
from app.core.rules.base import ProvinceRule, StandardProvinceRule
from app.core.rules.beijing import BeijingRule
from app.core.rules.hainan import HainanRule
from app.core.rules.shandong import ShandongRule
from app.core.rules.shanghai import ShanghaiRule
from app.core.rules.tianjin import TianjinRule
from app.core.rules.zhejiang import ZhejiangRule

__all__ = [
    "PROVINCES",
    "RULES",
    "ProvinceRule",
    "StandardProvinceRule",
    "all_rules",
    "batch_by_code",
    "get_rule",
]

RULES: dict[str, ProvinceRule] = {
    "beijing": BeijingRule(),
    "hainan": HainanRule(),
    "shandong": ShandongRule(),
    "shanghai": ShanghaiRule(),
    "tianjin": TianjinRule(),
    "zhejiang": ZhejiangRule(),
}

PROVINCES: tuple[str, ...] = tuple(sorted(RULES))


def get_rule(province: str) -> ProvinceRule:
    """按省份代码取规则包；未知省份抛 KeyError（宁可不答，不猜规则）。"""
    try:
        return RULES[province]
    except KeyError:
        raise KeyError(
            f"未支持的省份 {province!r}；已支持：{', '.join(PROVINCES)}"
        ) from None


def all_rules() -> list[ProvinceRule]:
    return [RULES[p] for p in PROVINCES]


def batch_by_code(batch_code: str) -> tuple[ProvinceRule, BatchRule]:
    """按批次编码定位（省, 批次），供 M3 元数据接口与志愿表校验使用。"""
    for rule in all_rules():
        for batch in rule.batches:
            if batch.batch_code == batch_code:
                return rule, batch
    raise KeyError(f"未知批次编码 {batch_code!r}")
