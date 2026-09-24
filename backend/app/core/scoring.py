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
# §5.4 学费 —— ★ ADR-022：学费的**打分维度已移除**
# ---------------------------------------------------------------------------
# 用户要求：学费不再是筛选条件、也不再参与效用打分。
# 但 `AdmissionUnit.tuition` 数据与卡片/报告上的学费展示**保留** ——
# 名师铁律 10 仍要求中外合作 / 民办 / 独立学院的学费必须在卡片上明示。
# 因此这里不再有 TUITION_SCORE_* 常量，也不再提供 tuition_score()。


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


def region_score(
    intended_regions: Sequence[str],
    college_province: str | None,
    *,
    home_province: str | None = None,
) -> float:
    """地区得分（DOMAIN_RULES.md §5.3 / ADR-019）。

    **有意向地区时**（原语义不变）：
    勾选命中 = 1.00；"可接受" = 0.50；未命中 = 0.00。

    **无意向地区时**（★ ADR-019 变更）：不再一律给 1.00 —— 那等于"地区维度完全不参与排序"，
    与"考虑考生偏向的地区以及该地区学校的综合实力"相悖。改为按两条**名师实务**规则给分：

    * **本省认可度**：院校所在地 == 考生本省 → **1.00**
      （本地校友网络、实习与就业半径、省内认可度，是真实存在的优势）；
    * **地区高教资源密度**：外省 → ``0.55 + 0.30 × region_strength_index(该省)``
      ∈ [0.55, 0.85]，即**高教资源越密集的地区得分越高**，但仍**低于本省**。

    若连考生本省都不知道（``home_province`` 为空）→ 返回 1.00（不限制，不猜）。
    """
    if intended_regions:
        if college_province and college_province in intended_regions:
            return 1.00
        if "可接受" in intended_regions:
            return 0.50
        return 0.00

    # 无意向地区：仅在知道考生本省时才做区分（不知道就不能否决）
    if not home_province:
        return 1.00
    if college_province and college_province == home_province:
        return 1.00
    strength = region_strength_index(college_province)
    if strength is None:
        # 院校所在地未知 → 给"外省中位"分，不因为缺数据而重罚
        return REGION_AWAY_BASE + REGION_AWAY_SPAN / 2
    return REGION_AWAY_BASE + REGION_AWAY_SPAN * strength


# ---------------------------------------------------------------------------
# §5.3 地区高教资源密度（★ ADR-019，数据驱动）
# ---------------------------------------------------------------------------
#: 各省「双一流及以上」院校数量 —— **由 `etl/catalog.py` 的人工院校名册统计得出**，
#: 不是估计值也不是 LLM 判断。统计口径 = tier ∈ {985, 211, SY} 的院校数。
#: 复算命令见 docs/MAJOR_TAXONOMY.md 同级的 ADR-019；总数 140 所 / 31 省。
#: 用途：只作为「地区高教资源密度」这一**上下文**维度，**不是**对单所院校的质量判断
#: （江苏的普通院校并不比甘肃的顶尖院校强——院校层次由 level_score 单独负责）。
REGION_TOP_COLLEGE_COUNT: dict[str, int] = {
    "beijing": 31, "shanghai": 14, "jiangsu": 15, "guangdong": 8, "sichuan": 8,
    "hubei": 7, "shaanxi": 7, "tianjin": 5, "heilongjiang": 4, "hunan": 4,
    "liaoning": 4, "anhui": 3, "jilin": 3, "shandong": 3, "zhejiang": 3,
    "chongqing": 2, "fujian": 2, "henan": 2, "shanxi": 2, "xinjiang": 2,
    "gansu": 1, "guangxi": 1, "guizhou": 1, "hainan": 1, "hebei": 1,
    "jiangxi": 1, "neimenggu": 1, "ningxia": 1, "qinghai": 1, "xizang": 1,
    "yunnan": 1,
}

#: 归一化分母 = 名册里最多的省（北京 31 所）
REGION_STRENGTH_MAX = 31

#: 外省地区得分 = BASE + SPAN × 密度 ∈ [0.55, 0.85]，**始终低于本省的 1.00**
REGION_AWAY_BASE = 0.55
REGION_AWAY_SPAN = 0.30


def region_strength_index(province: str | None) -> float | None:
    """该省「高教资源密度」，归一到 ``[0, 1]``；省份未知/不在名册 → ``None``（不猜）。

    ⚠️ 语义边界：这是**地区整体资源密度**，不是院校质量。
    浙江只有 3 所双一流（高教资源相对其经济体量偏少），但这**不代表**浙江的省重点
    院校差 —— 单所院校的质量由 :func:`level_score` 负责，本地认可度由
    :func:`region_score` 的"本省 1.00"负责。三者刻意分开。
    """
    if not province:
        return None
    count = REGION_TOP_COLLEGE_COUNT.get(province)
    if count is None:
        return None
    return min(1.0, count / REGION_STRENGTH_MAX)


def city_score(city: str | None) -> float:
    """城市得分（DOMAIN_RULES.md §5.3）；未收录城市按"其他"。"""
    tier = CITY_TIERS.get(city or "", "其他")
    return CITY_TIER_SCORES[tier]


def misc_score(college: College | None) -> float:
    """其他加分项（保研率 / 硕士点 / 博士点），归一后加权。"""
    if college is None:
        return 0.50
    postgrad = min(1.0, max(0.0, (college.postgrad_rate or 0.0) / 0.50))
    masters = min(1.0, max(0.0, (college.master_points or 0) / 50.0))
    doctors = min(1.0, max(0.0, (college.doctor_points or 0) / 40.0))
    return 0.5 * postgrad + 0.3 * masters + 0.2 * doctors


def normalize_weights(preferences: Preferences) -> dict[str, float]:
    """权重归一化到 1.0；全为 0 时退化为等权（§6.5）。

    ★ ADR-022：学费维度已移除（用户要求），现在是 **5 个维度**。
    """
    raw: dict[str, float] = {
        "region": max(0.0, preferences.weight_region),
        "college_level": max(0.0, preferences.weight_college_level),
        "major": max(0.0, preferences.weight_major),
        "city": max(0.0, preferences.weight_city),
        "misc": max(0.0, preferences.weight_misc),
    }
    total = sum(raw.values())
    if total <= 0:
        equal = 1.0 / len(raw)
        return {key: equal for key in raw}
    return {key: value / total for key, value in raw.items()}


def utility_of(breakdown: ScoreBreakdown, weights: Mapping[str, float]) -> float:
    """``utility = Σ w_k · score_k``（学费维度已移除，ADR-022）。"""
    return (
        weights.get("region", 0.0) * breakdown.region_score
        + weights.get("college_level", 0.0) * breakdown.college_level_score
        + weights.get("major", 0.0) * breakdown.major_match_score
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
    home_province: str | None = None,
) -> ScoredUnit:
    """对一个投档单位打分，返回带 ``score_breakdown`` 的 :class:`ScoredUnit`。

    :param home_province: 考生**本省**（``StudentProfile.province``）。用于地区维度的
        「本省认可度」与「地区高教资源密度」（ADR-019）。缺省时地区维度退回"不限制"。
    """
    preferences = preferences or Preferences()
    tags = level_tags if level_tags is not None else (college.level_tags if college else ())
    taxonomy = resolve_major_taxonomy(major, unit.major_name)
    match_score, match_level = major_match_detail(
        preferences.intended_major_categories, major=major, major_name=unit.major_name
    )
    college_province = college.province if college else unit.college_id.split("-", 1)[0]

    breakdown = ScoreBreakdown(
        region_score=region_score(
            preferences.intended_regions, college_province, home_province=home_province
        ),
        # ★ 审计字段：地区得分是怎么来的（ADR-019）
        region_strength=region_strength_index(college_province),
        is_home_province=bool(
            home_province and college_province and college_province == home_province
        ),
        college_level_score=level_score(
            tags,
            is_public=college.is_public if college else True,
            affiliation=college.affiliation if college else None,
        ),
        # 层次判别的依据（★ 不只看 985/211/双一流，ADR-019）
        level_tags=list(tags),
        college_affiliation=college.affiliation if college else None,
        college_is_public=college.is_public if college else None,
        major_match_score=match_score,
        major_match_level=match_level,
        major_discipline=taxonomy.discipline,
        major_category=taxonomy.category,
        admission_direction=taxonomy.direction,
        direction_kind=taxonomy.direction_kind,
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
    "REGION_AWAY_BASE",
    "REGION_AWAY_SPAN",
    "REGION_STRENGTH_MAX",
    "REGION_TOP_COLLEGE_COUNT",
    "RELATED_CATEGORY_MAP",
    "city_score",
    "level_score",
    "major_match_detail",
    "major_match_score",
    "misc_score",
    "normalize_weights",
    "region_score",
    "region_strength_index",
    "resolve_major_taxonomy",
    "score_unit",
    "utility_of",
]
