"""软偏好效用测试（AGENTS.md §6.5 / DOMAIN_RULES.md §5）。"""

from __future__ import annotations

import pytest

from app.core.models import College, Major, Preferences
from app.core.scoring import (
    CITY_TIERS,
    REGION_AWAY_BASE,
    REGION_AWAY_SPAN,
    REGION_TOP_COLLEGE_COUNT,
    city_score,
    level_score,
    major_match_detail,
    major_match_score,
    misc_score,
    normalize_weights,
    region_score,
    region_strength_index,
    score_unit,
    tuition_score,
    utility_of,
)

from factories import make_unit


def _college(**kwargs: object) -> College:
    data: dict[str, object] = {"id": "zhejiang-1001", "code": "1001", "name": "测试大学", "province": "zhejiang", "city": "杭州"}
    data.update(kwargs)
    return College(**data)  # type: ignore[arg-type]


def _major(**kwargs: object) -> Major:
    data: dict[str, object] = {
        "id": "工学-100111",
        "code": "100111",
        "name": "计算机科学与技术",
        "category": "工学",
        "discipline": "计算机类",
    }
    data.update(kwargs)
    return Major(**data)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 分项
# ---------------------------------------------------------------------------
def test_level_score_tiers() -> None:
    assert level_score(["985", "211", "双一流"]) == 1.00
    assert level_score(["211", "双一流"]) == 0.85
    assert level_score(["双一流"]) == 0.75
    assert level_score([], affiliation="教育部") == 0.60
    assert level_score([], is_public=True) == 0.45
    assert level_score([], is_public=False) == 0.20


def test_major_match_levels() -> None:
    major = _major()
    assert major_match_score(["计算机科学与技术"], major=major) == 1.00
    assert major_match_score(["计算机类"], major=major) == 0.80
    assert major_match_score(["工学"], major=major) == 0.55
    assert major_match_score(["理学"], major=major) == 0.30  # 相关门类
    assert major_match_score(["医学"], major=major) == 0.00
    assert major_match_score([], major=major) == 1.00  # 未填意向 = 不限制


def test_major_match_falls_back_to_taxonomy_without_major_row() -> None:
    """★ ADR-018：``major`` 行为空时，仍应能从**专业名**推出专业类并匹配。

    原实现要求调用方先查出 ``Major`` 行且该行的 ``category``/``discipline`` 非空；
    浙江真实数据的这两列曾是 NULL，于是"同一专业类/同一门类"两档**永不命中**。
    现在改为纯函数分类兜底 —— 这条用例守住该能力。
    """
    # 无 Major 行，只有专业名 → 专业类仍可推出
    assert major_match_score(["计算机类"], major=None, major_name="软件工程") == 0.80
    assert major_match_score(["工学"], major=None, major_name="软件工程") == 0.55
    assert major_match_score(["文学"], major=None, major_name="软件工程") == 0.00
    # 带招生方向的专业名：方向被剥离后再匹配（"基础拔尖基地班"不是专业名）
    assert (
        major_match_score(
            ["计算机科学与技术"], major=None, major_name="计算机科学与技术(基础拔尖基地班)"
        )
        == 1.00
    )
    assert (
        major_match_score(
            ["计算机类"], major=None, major_name="计算机科学与技术(基础拔尖基地班)"
        )
        == 0.80
    )
    # 无法归类的名字**不猜**（宁可不答）
    assert major_match_score(["计算机类"], major=None, major_name="不存在专业XYZ") == 0.00


def test_major_match_ignores_direction_words_as_intent() -> None:
    """意向里误填"中外合作办学"这类**方向词**时，不应把专业判成不匹配。

    方向词是筛选条件（filters.py 的职责），不是专业意向。
    """
    assert major_match_score(["中外合作办学"], major=None, major_name="软件工程") == 1.00
    assert major_match_score(["中外合作办学"], major=None, major_name="法学") == 1.00


def test_major_match_detail_reports_level() -> None:
    """每个分数必须能追溯到具体规则（DOMAIN_RULES §5）。"""
    assert major_match_detail(["计算机类"], major_name="软件工程") == (0.80, "SAME_DISCIPLINE")
    assert major_match_detail(["工学"], major_name="软件工程") == (0.55, "SAME_CATEGORY")
    assert major_match_detail(["理学"], major_name="软件工程") == (0.30, "RELATED_CATEGORY")
    assert major_match_detail(["医学"], major_name="软件工程") == (0.00, "NONE")
    assert major_match_detail([], major_name="软件工程") == (1.00, "NO_INTENT")
    assert major_match_detail(["软件工程"], major_name="软件工程") == (1.00, "EXACT_MAJOR")


def test_region_and_city_scores() -> None:
    assert region_score([], "zhejiang") == 1.00
    assert region_score(["zhejiang"], "zhejiang") == 1.00
    assert region_score(["可接受"], "beijing") == 0.50
    assert region_score(["zhejiang"], "beijing") == 0.00
    assert city_score("北京") == 1.00
    assert city_score("杭州") == 0.85
    assert city_score("合肥") == 0.85
    assert city_score("厦门") == 0.70
    assert city_score("湖州") == 0.50
    assert city_score("某不存在的城市") == 0.35
    assert city_score(None) == 0.35
    assert set(CITY_TIERS.values()) <= {"一线", "新一线", "二线", "三线"}


# ---------------------------------------------------------------------------
# 地区高教资源密度 + 本省认可度（ADR-019）
# ---------------------------------------------------------------------------
def test_region_strength_is_data_derived_and_bounded() -> None:
    """密度指数来自名册统计，必须落在 (0,1]，且北京（31 所）为最大值。"""
    assert region_strength_index("beijing") == 1.0
    assert region_strength_index("zhejiang") == pytest.approx(3 / 31)
    for province in REGION_TOP_COLLEGE_COUNT:
        value = region_strength_index(province)
        assert value is not None and 0.0 < value <= 1.0
    # 未知省份 → None（不猜）
    assert region_strength_index(None) is None
    assert region_strength_index("atlantis") is None
    assert region_strength_index("") is None


def test_region_strength_never_judges_single_college_quality() -> None:
    """★ 语义边界：密度只描述**地区整体资源**，不用于单所院校质量判断。

    浙江只有 3 所双一流（密度低于江苏），但这不代表浙工大差 ——
    所以"本省"必须拿满分，不能被密度拉低。
    """
    zj = region_score([], "zhejiang", home_province="zhejiang")
    js = region_score([], "jiangsu", home_province="zhejiang")
    assert zj == 1.00, "本省必须满分（本地认可度）"
    assert region_strength_index("zhejiang") < region_strength_index("jiangsu")
    assert zj > js, "即使本省密度更低，本省仍应高于外省"


def test_region_score_without_intent_uses_home_and_strength() -> None:
    """无意向地区时不再一律 1.00 —— 否则地区维度完全不参与排序。"""
    home = "zhejiang"
    assert region_score([], home, home_province=home) == 1.00
    beijing = region_score([], "beijing", home_province=home)
    qinghai = region_score([], "qinghai", home_province=home)
    # 外省得分 ∈ [BASE, BASE+SPAN]，且**始终低于本省**
    assert REGION_AWAY_BASE <= qinghai < beijing <= REGION_AWAY_BASE + REGION_AWAY_SPAN
    assert beijing < 1.00, "外省不得与本省同分"


def test_region_score_unknown_home_stays_unrestricted() -> None:
    """不知道考生本省 → 不能区别对待（不知道就不能否决）。"""
    assert region_score([], "beijing", home_province=None) == 1.00
    assert region_score([], "qinghai", home_province=None) == 1.00


def test_region_score_explicit_intent_semantics_unchanged() -> None:
    """有意向地区时保持原语义（勾选 1.0 / 可接受 0.5 / 未命中 0.0）。"""
    home = "zhejiang"
    assert region_score(["zhejiang"], "zhejiang", home_province=home) == 1.00
    assert region_score(["可接受"], "beijing", home_province=home) == 0.50
    assert region_score(["zhejiang"], "beijing", home_province=home) == 0.00
    # 有意向时"本省"不再自动满分（尊重考生明确选择）
    assert region_score(["beijing"], "zhejiang", home_province=home) == 0.00


def test_region_score_unknown_college_province_not_punished() -> None:
    """院校所在地缺失 → 给外省中位分，不因缺数据重罚。"""
    value = region_score([], None, home_province="zhejiang")
    assert value == pytest.approx(REGION_AWAY_BASE + REGION_AWAY_SPAN / 2)


# ---------------------------------------------------------------------------
# 院校层次判别：不只看 985/211/双一流（ADR-019）
# ---------------------------------------------------------------------------
def test_level_score_recognises_provincial_key_universities() -> None:
    """★ 省重点院校没有 985/211 标签，但不应被当成"普通公办"。

    实测缺陷：231 所省重点（浙工大、杭电、浙工商…）层次标签为空、affiliation 也为空，
    只拿 0.45；名册里它们本是 PROV tier。
    """
    assert level_score([], affiliation="省重点建设高校") == 0.60
    assert level_score([], affiliation="省部共建") == 0.60
    # 有标签时标签优先
    assert level_score(["双一流"], affiliation="省重点建设高校") == 0.75


def test_level_score_private_is_lowest() -> None:
    """民办/独立学院必须落到最低档（名师铁律 10 的学费明示依据）。"""
    assert level_score([], is_public=False) == 0.20
    assert level_score(["985"], is_public=False) == 1.00  # 标签优先


def test_level_score_ordering_is_sane() -> None:
    assert (
        level_score(["985"])
        > level_score(["211"])
        > level_score(["双一流"])
        > level_score([], affiliation="省重点建设高校")
        > level_score([])
        > level_score([], is_public=False)
    )


def test_tuition_score_branches() -> None:
    assert tuition_score(5000) == 1.00  # 未设预算
    assert tuition_score(5000, budget_comfortable=6000, budget_max=20000) == 1.00
    mid = tuition_score(13000, budget_comfortable=6000, budget_max=20000)
    assert 0.30 <= mid < 1.00
    assert tuition_score(25000, budget_comfortable=6000, budget_max=20000) == 0.00
    # 只设舒适线
    assert tuition_score(99999, budget_comfortable=6000) == 1.00
    # 只设硬上限
    assert 0.30 <= tuition_score(15000, budget_max=20000) <= 1.00


def test_misc_score_uses_college_metrics() -> None:
    assert misc_score(None) == 0.50
    strong = _college(postgrad_rate=0.55, master_points=60, doctor_points=50)
    weak = _college(postgrad_rate=0.0, master_points=0, doctor_points=0)
    assert misc_score(strong) == pytest.approx(1.0)
    assert misc_score(weak) == 0.0


# ---------------------------------------------------------------------------
# 权重与总效用
# ---------------------------------------------------------------------------
def test_normalize_weights_defaults_to_equal() -> None:
    equal = normalize_weights(Preferences())
    assert sum(equal.values()) == pytest.approx(1.0)
    assert len(set(equal.values())) == 1

    zeroed = normalize_weights(
        Preferences(
            weight_region=0,
            weight_college_level=0,
            weight_major=0,
            weight_tuition=0,
            weight_city=0,
            weight_misc=0,
        )
    )
    assert all(value == pytest.approx(1 / 6) for value in zeroed.values())

    skewed = normalize_weights(Preferences(weight_major=3.0))
    assert sum(skewed.values()) == pytest.approx(1.0)
    assert skewed["major"] > skewed["city"]


def test_score_unit_produces_traceable_breakdown() -> None:
    unit = make_unit(tuition=6000)
    preferences = Preferences(
        intended_regions=["zhejiang"],
        intended_major_categories=["计算机类"],
        budget_comfortable=8000,
        budget_max=30000,
    )
    scored = score_unit(unit, preferences=preferences, college=_college(city="杭州"), major=_major())
    assert scored.unit.unit_id == unit.unit_id
    breakdown = scored.score_breakdown
    for value in (
        breakdown.region_score,
        breakdown.college_level_score,
        breakdown.major_match_score,
        breakdown.tuition_score,
        breakdown.city_score,
        breakdown.misc_score,
    ):
        assert 0.0 <= value <= 1.0
    assert breakdown.region_score == 1.00
    assert breakdown.major_match_score == 0.80
    assert breakdown.city_score == 0.85
    assert 0.0 <= scored.utility <= 1.0
    assert scored.utility == pytest.approx(utility_of(breakdown, normalize_weights(preferences)))


def test_score_unit_without_college_or_major_still_works() -> None:
    scored = score_unit(make_unit(), preferences=Preferences())
    assert scored.utility > 0
    assert scored.score_breakdown.college_level_score == 0.45  # 默认公办普通本科
