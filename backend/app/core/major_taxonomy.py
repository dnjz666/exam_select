"""专业分类器 —— 四级：门类 → 专业类 → 专业 → 招生方向（纯函数，ADR-003）。

## 为什么需要它（M6 实测缺陷）

浙江真实数据里 ``majors.category`` 与 ``majors.discipline`` **全部为 NULL**
（``etl/loaders/zhejiang.py`` 原先把这两列硬编码成 ``None``，因为官方投档表
只发布专业名，不发布专业目录归属）。后果是：

* ``scoring.major_match_score`` 里"同一专业类 0.80 / 同一门类 0.55 / 相关门类 0.30"
  这三档**永远命中不了** —— 只有"专业名完全一致"能拿分；
* ``probability`` Step 0 的类比池 ``analog_key(..., discipline)`` 对浙江全部塌缩成
  ``discipline=None`` 一个桶，类比质量下降；
* 前端"意向专业"筛选形同虚设。

本模块把**招生专业名**确定性地映射回教育部专业目录的**门类 / 专业类**，
从而让上述三处重新工作。

## 四级模型

| 级别 | 名称 | 取值来源 | 例 |
|---|---|---|---|
| L1 | 门类 | 教育部本科目录 12 门类（专科为 19 大类） | 工学 |
| L2 | 专业类 | 教育部本科目录 93 专业类 | 计算机类 |
| L3 | 专业 | 去括号后的专业基名 | 计算机科学与技术 |
| L4 | 招生方向 | 括号内后缀 | (中外合作办学) |

## 判定优先级（先命中先返回，绝不"猜"）

1. ``CATALOG_EXACT`` —— 基名精确命中目录专业名（``MAJOR_EXACT``）
2. ``DISCIPLINE_NAME`` —— 基名本身就是一个专业类名（如"计算机类"）
3. ``TRAINING_CLASS`` —— 试验班大类招生（如"工科试验班"），门类来自
   ``TRAINING_CLASS_RULES``；若方向括号可收窄到具体专业类则用 ``DIRECTION_NARROWED``
4. ``KEYWORD_RULE`` —— 命中 ``DISCIPLINE_KEYWORDS``（**最长关键词优先**，避免
   "机械"抢走"机械电子工程"以外的更长匹配）
5. ``UNCLASSIFIED`` —— 都不命中 → 门类与专业类均为 ``None``

★ **宁可不答，不可编造**：第 5 档不做任何"看起来合理"的兜底猜测。
``UNCLASSIFIED`` 会在 ``scoring`` 里按"不匹配"处理，并由调用方决定是否提示。

★ 专科（``duration=3``）专业名用同一套本科专业类词汇归类（项目内部约定，
``level=ZHUANKE`` 时 ``evidence`` 会标注），因为最终消费方是"专业类匹配打分"，
需要**单一可比的专业类空间**。这不是教育部口径，已在 ``docs/MAJOR_TAXONOMY.md`` 声明。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

from app.core.major_taxonomy_data import (
    BENKE_CATEGORIES,
    DIRECTION_CATEGORY,
    DIRECTION_KINDS,
    DIRECTION_NARROWING,
    DISCIPLINE_KEYWORDS,
    MAJOR_EXACT,
    MAJOR_EXACT_BY_LEVEL,
    SOURCE,
    TRAINING_CLASS_RULES,
    ZHUANKE_CATEGORIES,
)

# ---------------------------------------------------------------------------
# 反向索引（模块级构建一次；纯计算，无 IO）
# ---------------------------------------------------------------------------
DISCIPLINE_TO_CATEGORY: dict[str, str] = {
    discipline: category
    for category, disciplines in BENKE_CATEGORIES.items()
    for discipline in disciplines
}
ZHUANKE_DISCIPLINE_TO_CATEGORY: dict[str, str] = {
    discipline: category
    for category, disciplines in ZHUANKE_CATEGORIES.items()
    for discipline in disciplines
}
#: **本科 ∪ 专科** 的完整专业类 → 门类/大类映射。
#: 专科专业名用同一套词汇归类（见模块 docstring），因此规则库的值域校验
#: 与 ``category_of`` 都必须用这个并集，否则会误判合法规则为非法。
ALL_DISCIPLINE_TO_CATEGORY: dict[str, str] = {
    **ZHUANKE_DISCIPLINE_TO_CATEGORY,
    **DISCIPLINE_TO_CATEGORY,
}
ALL_DISCIPLINES: tuple[str, ...] = tuple(ALL_DISCIPLINE_TO_CATEGORY)

#: 关键词规则按**关键词长度降序**排好，保证"最长匹配优先"
_KEYWORD_RULES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        ((kw, disc) for disc, kws in DISCIPLINE_KEYWORDS.items() for kw in kws),
        key=lambda pair: (-len(pair[0]), pair[0]),
    )
)

#: 方向收窄规则同样按关键词长度降序
_NARROWING_RULES: tuple[tuple[str, str], ...] = tuple(
    sorted(DIRECTION_NARROWING.items(), key=lambda pair: (-len(pair[0]), pair[0]))
)

#: 方向 → 门类（只能定到门类、定不到专业类时使用），同样最长优先
_DIRECTION_CATEGORY_RULES: tuple[tuple[str, str], ...] = tuple(
    sorted(DIRECTION_CATEGORY.items(), key=lambda pair: (-len(pair[0]), pair[0]))
)

#: 大类招生（试验班/实验班/创新班）名称后缀 —— 用于识别目录里没有登记的新试验班名
_TRAINING_CLASS_SUFFIXES: tuple[str, ...] = (
    "试验班类",
    "试验班",
    "实验班",
    "创新班",
    "基地班",
)

#: 方向类型匹配规则（按关键词长度降序；MAJOR_DIRECTION 无关键词，作兜底）
_DIRECTION_RULES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            (kw, kind)
            for kind, spec in DIRECTION_KINDS.items()
            for kw in spec.get("keywords", ())
        ),
        key=lambda pair: (-len(pair[0]), pair[0]),
    )
)

#: 招生方向类型的**中文标签**集合 —— 用于识别"意向专业"里误填的方向词
#: （如把"中外合作办学"填进意向专业）。这类词是**筛选条件**，不该参与专业匹配打分。
DIRECTION_KIND_LABELS: frozenset[str] = frozenset(
    spec["label"] for spec in DIRECTION_KINDS.values()
) | frozenset(
    keyword for spec in DIRECTION_KINDS.values() for keyword in spec.get("keywords", ())
)

_PAREN_RE = re.compile(r"[（(]([^（）()]*)[)）]")

LEVEL_BENKE = "BENKE"
LEVEL_ZHUANKE = "ZHUANKE"
LEVEL_UNKNOWN = "UNKNOWN"


class TaxonomyStatus(str, Enum):
    """分类判定来源。★ 用于审计"这个门类是怎么定出来的"。"""

    CATALOG_EXACT = "CATALOG_EXACT"
    DISCIPLINE_NAME = "DISCIPLINE_NAME"
    TRAINING_CLASS = "TRAINING_CLASS"
    DIRECTION_NARROWED = "DIRECTION_NARROWED"
    KEYWORD_RULE = "KEYWORD_RULE"
    UNCLASSIFIED = "UNCLASSIFIED"


class MajorTaxonomy(NamedTuple):
    """一个招生专业名的四级分类结果。"""

    raw_name: str
    base_name: str
    level: str
    category: str | None
    discipline: str | None
    direction: str | None
    direction_kind: str | None
    status: TaxonomyStatus
    evidence: str
    source_url: str

    @property
    def has_discipline(self) -> bool:
        """专业类（L2）是否已确定 —— 决定能否走"同一专业类"打分档与类比池。"""
        return self.discipline is not None

    @property
    def is_classified(self) -> bool:
        """是否至少定到了门类（L1）或专业类（L2）。

        ★ 注意区分：``TRAINING_CLASS`` 的试验班只定到门类（``discipline=None``），
        它是"已分类但专业类未知"，与 ``UNCLASSIFIED``（什么都没定出来）不同。
        """
        return self.category is not None or self.discipline is not None


def split_direction(name: str) -> tuple[str, str | None]:
    """把 ``"计算机类(中外合作办学)"`` 拆成 ``("计算机类", "中外合作办学")``。

    多个括号段用空格连接；无括号 → ``(name, None)``。
    """
    text = (name or "").strip()
    if not text:
        return "", None
    found = [m.group(1).strip() for m in _PAREN_RE.finditer(text)]
    base = _PAREN_RE.sub("", text).strip()
    direction = " ".join(part for part in found if part) or None
    return base or text, direction


def classify_direction(direction: str | None) -> str | None:
    """把方向文本归入 ``DIRECTION_KINDS`` 之一；无方向 → ``None``。

    兜底为 ``MAJOR_DIRECTION``（"括号内是专业方向说明"），**不会**返回 None 以外的猜测。
    """
    if not direction:
        return None
    for keyword, kind in _DIRECTION_RULES:
        if keyword in direction:
            return kind
    return "MAJOR_DIRECTION"


def category_of(discipline: str | None) -> str | None:
    """专业类 → 门类。未知专业类 → ``None``（不猜）。"""
    if not discipline:
        return None
    return ALL_DISCIPLINE_TO_CATEGORY.get(discipline)


def _match_keyword(base_name: str) -> tuple[str, str] | None:
    """最长关键词优先的规则匹配；无命中 → ``None``。"""
    for keyword, discipline in _KEYWORD_RULES:
        if keyword in base_name:
            return keyword, discipline
    return None


def _narrow_by_direction(direction: str | None) -> tuple[str, str] | None:
    """试验班的方向括号 → 具体专业类；无命中 → ``None``。"""
    if not direction:
        return None
    for keyword, discipline in _NARROWING_RULES:
        if keyword in direction:
            return keyword, discipline
    return None


def _category_by_direction(direction: str | None) -> tuple[str, str] | None:
    """方向括号 → 门类（只到门类一级）；无命中 → ``None``。"""
    if not direction:
        return None
    for keyword, category in _DIRECTION_CATEGORY_RULES:
        if keyword in direction:
            return keyword, category
    return None


def _is_training_class(base_name: str) -> bool:
    """是否是"大类招生"式的专业名（试验班 / 实验班 / 创新班 / 基地班）。"""
    if base_name in TRAINING_CLASS_RULES:
        return True
    return base_name.endswith(_TRAINING_CLASS_SUFFIXES)


def classify_major(name: str, *, level: str | None = None) -> MajorTaxonomy:
    """把一个招生专业名分类到「门类 / 专业类 / 专业 / 招生方向」。

    :param name: 招生专业名原文（可含括号方向），如 ``"计算机类(中外合作办学)"``。
    :param level: ``"BENKE"`` / ``"ZHUANKE"`` / ``None``（未知）。仅用于标注与审计，
        **不改变**归类结果（专科用同一套专业类词汇，见模块 docstring）。

    纯函数：同一输入必然同一输出，无 IO。
    """
    base, direction = split_direction(name)
    direction_kind = classify_direction(direction)
    resolved_level = level or LEVEL_UNKNOWN
    src = str(SOURCE.get("benke_source_url", ""))

    def build(
        discipline: str | None,
        status: TaxonomyStatus,
        evidence: str,
        *,
        category: str | None = None,
    ) -> MajorTaxonomy:
        return MajorTaxonomy(
            raw_name=name,
            base_name=base,
            level=resolved_level,
            # 显式 category 优先（试验班只知道门类、不知道专业类的情形）
            category=category if category is not None else category_of(discipline),
            discipline=discipline,
            direction=direction,
            direction_kind=direction_kind,
            status=status,
            evidence=evidence,
            source_url=src,
        )

    if not base:
        return build(None, TaxonomyStatus.UNCLASSIFIED, "专业名为空")

    # 1) 目录精确名（★ 支持按学制分流，见 MAJOR_EXACT_BY_LEVEL）
    if base in MAJOR_EXACT:
        discipline = MAJOR_EXACT[base]
        override = MAJOR_EXACT_BY_LEVEL.get(base) or {}
        if resolved_level in override:
            # 例：人力资源管理 本科属工商管理类(120206)、专科属公共管理类(590202)。
            # 学制未知时**不猜**，用 major_exact 的默认（本科）口径并在 evidence 里注明。
            return build(
                override[resolved_level],
                TaxonomyStatus.CATALOG_EXACT,
                f"目录精确匹配：{base}（按学制 {resolved_level} 分流）",
            )
        note = ""
        if override:
            note = f"（该名在 {'/'.join(sorted(override))} 下有不同归属；本次学制={resolved_level}，按默认口径）"
        return build(
            discipline,
            TaxonomyStatus.CATALOG_EXACT,
            f"目录精确匹配：{base}{note}",
        )

    # 2) 基名本身就是专业类名（如「计算机类」「机械类」）
    if base in DISCIPLINE_TO_CATEGORY:
        return build(base, TaxonomyStatus.DISCIPLINE_NAME, f"基名即专业类：{base}")
    if base in ZHUANKE_DISCIPLINE_TO_CATEGORY:
        return build(
            base, TaxonomyStatus.DISCIPLINE_NAME, f"基名即专科专业类：{base}"
        )

    # 3) 试验班 / 实验班 / 创新班（大类招生）
    if _is_training_class(base):
        # 3a) 方向括号能收窄到**专业类** → 最好
        narrowed = _narrow_by_direction(direction)
        if narrowed is not None:
            keyword, discipline = narrowed
            return build(
                discipline,
                TaxonomyStatus.DIRECTION_NARROWED,
                f"大类招生「{base}」+ 方向「{direction}」收窄到专业类（命中「{keyword}」）",
            )
        # 3b) 登记在册的试验班名 → 门类
        if base in TRAINING_CLASS_RULES:
            category = TRAINING_CLASS_RULES[base]
            return build(
                None,
                TaxonomyStatus.TRAINING_CLASS,
                f"试验班大类招生「{base}」，门类={category}（未收窄到专业类）",
                category=category,
            )
        # 3c) 方向括号只能定到**门类**
        by_category = _category_by_direction(direction)
        if by_category is not None:
            keyword, category = by_category
            return build(
                None,
                TaxonomyStatus.TRAINING_CLASS,
                f"大类招生「{base}」+ 方向「{direction}」定到门类（命中「{keyword}」）",
                category=category,
            )
        # 3d) 知道是大类招生，但连门类也定不出来 → 诚实标注
        return build(
            None,
            TaxonomyStatus.TRAINING_CLASS,
            f"大类招生「{base}」：方向「{direction}」无法归类，不猜测",
        )

    # 4) 关键词规则
    hit = _match_keyword(base)
    if hit is not None:
        keyword, discipline = hit
        return build(
            discipline, TaxonomyStatus.KEYWORD_RULE, f"关键词「{keyword}」→ {discipline}"
        )

    # 5) 诚实兜底
    return build(None, TaxonomyStatus.UNCLASSIFIED, "未命中任何规则，不猜测")


def classify_many(
    names: list[str] | tuple[str, ...], *, level: str | None = None
) -> list[MajorTaxonomy]:
    """批量分类（保持输入顺序）。"""
    return [classify_major(n, level=level) for n in names]


def taxonomy_from_stored(
    name: str,
    category: str | None,
    discipline: str | None,
    *,
    level: str | None = None,
) -> MajorTaxonomy:
    """用**库里已回填**的门类/专业类构造结果；两者都为空时回退到 :func:`classify_major`。

    ★ 为什么需要它：真实数据的 ``majors.category/discipline`` 由装载器回填（ADR-018），
    是"已审计入库"的口径，应当**优先于**运行时重新分类。但招生方向（L4）与基名（L3）
    始终从专业名现算 —— 它们不落库，避免同一事实存两份而漂移。
    """
    if not category and not discipline:
        return classify_major(name, level=level)
    base, direction = split_direction(name)
    resolved = category or category_of(discipline)
    return MajorTaxonomy(
        raw_name=name,
        base_name=base,
        level=level or LEVEL_UNKNOWN,
        category=resolved,
        discipline=discipline,
        direction=direction,
        direction_kind=classify_direction(direction),
        status=TaxonomyStatus.CATALOG_EXACT if discipline else TaxonomyStatus.TRAINING_CLASS,
        evidence="取自库中已回填的门类/专业类（装载器 ADR-018）",
        source_url=str(SOURCE.get("benke_source_url", "")),
    )


__all__ = [
    "ALL_DISCIPLINES",
    "ALL_DISCIPLINE_TO_CATEGORY",
    "DIRECTION_KIND_LABELS",
    "DISCIPLINE_TO_CATEGORY",
    "LEVEL_BENKE",
    "LEVEL_UNKNOWN",
    "LEVEL_ZHUANKE",
    "MAJOR_EXACT_BY_LEVEL",
    "MajorTaxonomy",
    "SOURCE",
    "TaxonomyStatus",
    "ZHUANKE_DISCIPLINE_TO_CATEGORY",
    "category_of",
    "classify_direction",
    "classify_major",
    "classify_many",
    "split_direction",
    "taxonomy_from_stored",
]