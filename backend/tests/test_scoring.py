"""软偏好效用测试（AGENTS.md §6.5 / DOMAIN_RULES.md §5）。"""

from __future__ import annotations

import pytest

from app.core.models import College, Major, Preferences
from app.core.scoring import (
    CITY_TIERS,
    city_score,
    level_score,
    major_match_score,
    misc_score,
    normalize_weights,
    region_score,
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
    assert major_match_score(["计算机类"], major=None, major_name="软件工程") == 0.00


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
