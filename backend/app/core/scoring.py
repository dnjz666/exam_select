"""软偏好效用打分（AGENTS.md §6.5 / DOMAIN_RULES.md §5）。

- 每个分项归一到 ``[0, 1]``，且**每一项都能追溯到具体规则**（返回 ``ScoreBreakdown``）；
- 权重由考生设定，使用时归一化到 1.0；未设意向的维度按"不限制"处理（见各函数注释）；
- 纯函数，无 IO（ADR-003）。

⚠️ 城市分级（``CITY_TIERS``）为**项目内部约定**（依据公开的城市商业魅力分级惯例整理），
来源待补；M6 接入真实数据时必须替换为带 ``source_url`` 的分级表（DOMAIN_RULES.md §5.3）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.core.major_taxonomy import (
    DIRECTION_KIND_LABELS,
    MajorTaxonomy,
    split_direction,
    taxonomy_from_stored,
)
from app.core.models import (
    AdmissionUnit,
    College,
    Major,
    Preferences,
    ScoreBreakdown,
    ScoredUnit,
)

# ---------------------------------------------------------------------------
# §5.1 院校层次
# ---------------------------------------------------------------------------
LEVEL_SCORE_985 = 1.00
LEVEL_SCORE_211 = 0.85
LEVEL_SCORE_DOUBLE_FIRST_CLASS = 0.75
LEVEL_SCORE_PROVINCIAL_KEY = 0.60
LEVEL_SCORE_PUBLIC = 0.45
LEVEL_SCORE_PRIVATE = 0.20

#: 视为"省重点 / 部属"的隶属单位关键词
KEY_AFFILIATIONS = ("教育部", "部属", "省重点", "省部共建", "工业和信息化部", "中国科学院")

# ---------------------------------------------------------------------------
# §5.2 专业匹配
# ---------------------------------------------------------------------------
MAJOR_MATCH_EXACT = 1.00
MAJOR_MATCH_DISCIPLINE = 0.80
MAJOR_MATCH_CATEGORY = 0.55
MAJOR_MATCH_RELATED = 0.30
MAJOR_MATCH_NONE = 0.00

#: 匹配层级标签（★ 每个分数都要能追溯到具体规则，DOMAIN_RULES §5）
MATCH_LEVEL_NO_INTENT = "NO_INTENT"
MATCH_LEVEL_EXACT = "EXACT_MAJOR"
MATCH_LEVEL_DISCIPLINE = "SAME_DISCIPLINE"
MATCH_LEVEL_CATEGORY = "SAME_CATEGORY"
MATCH_LEVEL_RELATED = "RELATED_CATEGORY"
MATCH_LEVEL_NONE = "NONE"

#: 门类相关映射（"相关门类"判据，DOMAIN_RULES.md §5.2）
RELATED_CATEGORY_MAP: dict[str, tuple[str, ...]] = {
    "工学": ("理学", "管理学"),
    "理学": ("工学", "医学", "农学"),
    "医学": ("理学", "农学"),
    "农学": ("理学", "医学", "工学"),
    "经济学": ("管理学", "法学"),
    "管理学": ("经济学", "法学"),
    "法学": ("管理学", "经济学"),
    "教育学": ("文学", "法学"),
    "文学": ("教育学", "历史学", "艺术学"),
    "历史学": ("文学", "哲学"),
    "哲学": ("历史学", "法学"),
    "艺术学": ("文学", "教育学"),
}

# ---------------------------------------------------------------------------
# §5.3 城市分级（内部约定，来源待补）
# ---------------------------------------------------------------------------
CITY_TIER_SCORES: dict[str, float] = {
    "一线": 1.00,
    "新一线": 0.85,
    "二线": 0.70,
    "三线": 0.50,
    "其他": 0.35,
}
CITY_TIERS: dict[str, str] = {
    # 一线
    "北京": "一线", "上海": "一线", "广州": "一线", "深圳": "一线",
    # 新一线
    "成都": "新一线", "杭州": "新一线", "重庆": "新一线", "西安": "新一线", "苏州": "新一线",
    "武汉": "新一线", "南京": "新一线", "天津": "新一线", "长沙": "新一线", "郑州": "新一线",
    "东莞": "新一线", "青岛": "新一线", "宁波": "新一线", "佛山": "新一线", "合肥": "新一线",
    # 二线
    "厦门": "二线", "福州": "二线", "济南": "二线", "大连": "二线", "沈阳": "二线",
    "无锡": "二线", "昆明": "二线", "哈尔滨": "二线", "长春": "二线", "南昌": "二线",
    "贵阳": "二线", "南宁": "二线", "温州": "二线", "石家庄": "二线", "太原": "二线",
    "常州": "二线", "南通": "二线", "徐州": "二线", "泉州": "二线", "珠海": "二线",
    "烟台": "二线", "嘉兴": "二线", "绍兴": "二线", "金华": "二线", "台州": "二线",
    "保定": "二线", "兰州": "二线", "乌鲁木齐": "二线", "海口": "二线",
    # 三线（列举常见城市；未命中 → "其他"）
    "扬州": "三线", "镇江": "三线", "泰州": "三线", "盐城": "三线", "湖州": "三线",
    "丽水": "三线", "舟山": "三线", "芜湖": "三线", "蚌埠": "三线", "洛阳": "三线",
    "开封": "三线", "新乡": "三线", "淄博": "三线", "潍坊": "三线", "临沂": "三线",
    "聊城": "三线", "济宁": "三线", "泰安": "三线", "曲阜": "三线", "湛江": "三线",
    "汕头": "三线", "绵阳": "三线", "雅安": "三线", "延安": "三线", "杨凌": "三线",
    "秦皇岛": "三线", "唐山": "三线", "邯郸": "三线", "吉林": "三线", "四平": "三线",
    "延吉": "三线", "大庆": "三线", "齐齐哈尔": "三线", "衡阳": "三线", "湘潭": "三线",
    "吉首": "三线", "宜昌": "三线", "荆州": "三线", "马鞍山": "三线", "淮南": "三线",
    "赣州": "三线", "景德镇": "三线", "桂林": "三线", "三亚": "三线", "咸阳": "三线",
    "连云港": "三线", "芜湖县": "三线",
}

# ---------------------------------------------------------------------------
# §5.4 学费
# ---------------------------------------------------------------------------
TUITION_SCORE_COMFORTABLE = 1.00
TUITION_SCORE_FLOOR = 0.30


def level_score(
    level_tags: Sequence[str] | None = None,
    *,
    is_public: bool = True,
    affiliation: str | None = None,
) -> float:
    """院校层次得分（DOMAIN_RULES.md §5.1）。"""
    tags = set(level_tags or ())
    if "985" in tags:
        return LEVEL_SCORE_985
    if "211" in tags:
        return LEVEL_SCORE_211
    if "双一流" in tags:
        return LEVEL_SCORE_DOUBLE_FIRST_CLASS
    if affiliation and any(key in affiliation for key in KEY_AFFILIATIONS):
        return LEVEL_SCORE_PROVINCIAL_KEY
    if not is_public:
        return LEVEL_SCORE_PRIVATE
    return LEVEL_SCORE_PUBLIC


def resolve_major_taxonomy(
    major: Major | None = None, major_name: str = ""
) -> MajorTaxonomy:
    """取某专业的四级分类：**库里已回填的优先**，缺失时用分类器兜底（不写库）。

    ★ M6 实测缺陷（ADR-018）：浙江真实数据的 ``majors.category/discipline`` 原先是
    ``NULL``，导致下面 :func:`major_match_score` 的三档专业匹配**永不命中**。
    现在装载器已回填；本函数仍保留兜底，因为模拟数据与历史行也可能缺失。
    """
    name = major_name or (major.name if major else "")
    return taxonomy_from_stored(
        name,
        major.category if major else None,
        major.discipline if major else None,
    )


def major_match_detail(
    intended: Sequence[str],
    *,
    major: Major | None = None,
    major_name: str = "",
) -> tuple[float, str]:
    """专业匹配得分 + **匹配层级标签**（四级模型，ADR-018）。

    ``intended`` 可混合填写 **专业名 / 专业类 / 门类**（考生不必知道自己在填哪一级）。
    判定顺序（先命中先返回）：

    ==================  ======  ==========================================
    层级                 得分    含义
    ==================  ======  ==========================================
    ``EXACT_MAJOR``      1.00    意向里有该专业名（含去方向后的基名）
    ``SAME_DISCIPLINE``  0.80    同一**专业类**（如都在"计算机类"内）
    ``SAME_CATEGORY``    0.55    同一**学科门类**（如都在"工学"内）
    ``RELATED_CATEGORY`` 0.30    相关门类（``RELATED_CATEGORY_MAP``）
    ``NONE``             0.00    不在意向范围
    ==================  ======  ==========================================

    **未填写意向 → 1.00 / ``NO_INTENT``**（"不限制"≠"全都不匹配"，不加惩罚）。

    ★ 容错：意向里若混入了"中外合作办学""卓越工程师"这类**招生方向词**，会被忽略 ——
    它们是筛选条件（``filters.py`` 的职责），不该在这里把专业判成不匹配。
    """
    if not intended:
        return MAJOR_MATCH_EXACT, MATCH_LEVEL_NO_INTENT

    # 剔除误填的方向词；若剔除后为空，视为"没填有效意向"
    wanted = [
        w for w in intended if w and w not in DIRECTION_KIND_LABELS
    ]
    if not wanted:
        return MAJOR_MATCH_EXACT, MATCH_LEVEL_NO_INTENT

    name = major_name or (major.name if major else "")

    # ① 专业名精确匹配（原文 或 去招生方向后的基名）
    if name and name in wanted:
        return MAJOR_MATCH_EXACT, MATCH_LEVEL_EXACT
    base, _direction = split_direction(name)
    if base and base != name and base in wanted:
        return MAJOR_MATCH_EXACT, MATCH_LEVEL_EXACT

    # ②③④ 专业类 → 门类 → 相关门类
    taxonomy = resolve_major_taxonomy(major, major_name)
    if taxonomy.discipline and taxonomy.discipline in wanted:
        return MAJOR_MATCH_DISCIPLINE, MATCH_LEVEL_DISCIPLINE
    if taxonomy.category and taxonomy.category in wanted:
        return MAJOR_MATCH_CATEGORY, MATCH_LEVEL_CATEGORY
    related = RELATED_CATEGORY_MAP.get(taxonomy.category or "", ())
    if any(category in wanted for category in related):
        return MAJOR_MATCH_RELATED, MATCH_LEVEL_RELATED
    return MAJOR_MATCH_NONE, MATCH_LEVEL_NONE


def major_match_score(
    intended: Sequence[str],
    *,
    major: Major | None = None,
    major_name: str = "",
) -> float:
    """专业匹配得分（DOMAIN_RULES.md §5.2）；层级细节见 :func:`major_match_detail`。"""
    return major_match_detail(intended, major=major, major_name=major_name)[0]


def region_score(intended_regions: Sequence[str], college_province: str | None) -> float:
    """地区得分（DOMAIN_RULES.md §5.3）：勾选 1.0 / "可接受" 0.5 / 未勾选 0.0。

    未填写意向地区 → 1.00（不限制）。
    """
    if not intended_regions:
        return 1.00
    if college_province and college_province in intended_regions:
        return 1.00
    if "可接受" in intended_regions:
        return 0.50
    return 0.00


def city_score(city: str | None) -> float:
    """城市得分（DOMAIN_RULES.md §5.3）；未收录城市按"其他"。"""
    tier = CITY_TIERS.get(city or "", "其他")
    return CITY_TIER_SCORES[tier]


def tuition_score(
    tuition: int,
    *,
    budget_comfortable: int | None = None,
    budget_max: int | None = None,
) -> float:
    """学费得分（DOMAIN_RULES.md §5.4）。

    ``≤ comfortable`` → 1.00；``comfortable < t ≤ max`` → 线性降到 0.30；
    ``> max`` → 0.00（硬约束剔除由 filters.py 负责，这里只打分）。
    未设预算 → 1.00（不限制）。
    """
    if budget_max is None and budget_comfortable is None:
        return TUITION_SCORE_COMFORTABLE
    if budget_comfortable is not None and tuition <= budget_comfortable:
        return TUITION_SCORE_COMFORTABLE
    if budget_max is None:
        return TUITION_SCORE_COMFORTABLE
    if tuition > budget_max:
        return 0.00
    lower = budget_comfortable if budget_comfortable is not None else 0
    if budget_max <= lower:
        return TUITION_SCORE_FLOOR
    ratio = (tuition - lower) / (budget_max - lower)
    return max(TUITION_SCORE_FLOOR, TUITION_SCORE_COMFORTABLE - ratio * (TUITION_SCORE_COMFORTABLE - TUITION_SCORE_FLOOR))


def misc_score(college: College | None) -> float:
    """其他加分项（保研率 / 硕士点 / 博士点），归一后加权。"""
    if college is None:
        return 0.50
    postgrad = min(1.0, max(0.0, (college.postgrad_rate or 0.0) / 0.50))
    masters = min(1.0, max(0.0, (college.master_points or 0) / 50.0))
    doctors = min(1.0, max(0.0, (college.doctor_points or 0) / 40.0))
    return 0.5 * postgrad + 0.3 * masters + 0.2 * doctors


def normalize_weights(preferences: Preferences) -> dict[str, float]:
    """权重归一化到 1.0；全为 0 时退化为等权（§6.5）。"""
    raw: dict[str, float] = {
        "region": max(0.0, preferences.weight_region),
        "college_level": max(0.0, preferences.weight_college_level),
        "major": max(0.0, preferences.weight_major),
        "tuition": max(0.0, preferences.weight_tuition),
        "city": max(0.0, preferences.weight_city),
        "misc": max(0.0, preferences.weight_misc),
    }
    total = sum(raw.values())
    if total <= 0:
        equal = 1.0 / len(raw)
        return {key: equal for key in raw}
    return {key: value / total for key, value in raw.items()}


def utility_of(breakdown: ScoreBreakdown, weights: Mapping[str, float]) -> float:
    """``utility = Σ w_k · score_k``。"""
    return (
        weights.get("region", 0.0) * breakdown.region_score
        + weights.get("college_level", 0.0) * breakdown.college_level_score
        + weights.get("major", 0.0) * breakdown.major_match_score
        + weights.get("tuition", 0.0) * breakdown.tuition_score
        + weights.get("city", 0.0) * breakdown.city_score
        + weights.get("misc", 0.0) * breakdown.misc_score
    )


def score_unit(
    unit: AdmissionUnit,
    *,
    preferences: Preferences | None = None,
    college: College | None = None,
    major: Major | None = None,
    level_tags: Sequence[str] | None = None,
) -> ScoredUnit:
    """对一个投档单位打分，返回带 ``score_breakdown`` 的 :class:`ScoredUnit`。"""
    preferences = preferences or Preferences()
    tags = level_tags if level_tags is not None else (college.level_tags if college else ())
    taxonomy = resolve_major_taxonomy(major, unit.major_name)
    match_score, match_level = major_match_detail(
        preferences.intended_major_categories, major=major, major_name=unit.major_name
    )

    breakdown = ScoreBreakdown(
        region_score=region_score(
            preferences.intended_regions, (college.province if college else unit.college_id.split("-", 1)[0])
        ),
        college_level_score=level_score(
            tags,
            is_public=college.is_public if college else True,
            affiliation=college.affiliation if college else None,
        ),
        major_match_score=match_score,
        major_match_level=match_level,
        major_discipline=taxonomy.discipline,
        major_category=taxonomy.category,
        admission_direction=taxonomy.direction,
        direction_kind=taxonomy.direction_kind,
        tuition_score=tuition_score(
            unit.tuition,
            budget_comfortable=preferences.budget_comfortable,
            budget_max=preferences.budget_max,
        ),
        city_score=city_score(college.city if college else unit.campus),
        misc_score=misc_score(college),
    )
    weights = normalize_weights(preferences)
    return ScoredUnit(unit=unit, utility=utility_of(breakdown, weights), score_breakdown=breakdown)


__all__ = [
    "CITY_TIERS",
    "CITY_TIER_SCORES",
    "MATCH_LEVEL_CATEGORY",
    "MATCH_LEVEL_DISCIPLINE",
    "MATCH_LEVEL_EXACT",
    "MATCH_LEVEL_NONE",
    "MATCH_LEVEL_NO_INTENT",
    "MATCH_LEVEL_RELATED",
    "RELATED_CATEGORY_MAP",
    "city_score",
    "level_score",
    "major_match_detail",
    "major_match_score",
    "misc_score",
    "normalize_weights",
    "region_score",
    "resolve_major_taxonomy",
    "score_unit",
    "tuition_score",
    "utility_of",
]
