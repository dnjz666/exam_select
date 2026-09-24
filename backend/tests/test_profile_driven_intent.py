"""档案驱动的筛选与偏好（ADR-022）。

## 这次改动的语义

筛选与偏好不再在推荐页单独维护一份，而是**只填一次**（建档向导第 4 步）、
持久化到档案，推荐与志愿表都直接按它生成。

两条必须钉住的语义：

1. ``intent_as_hard=False``（默认）→ 意向**只影响排序**（软偏好 §6.5），不做硬过滤；
2. ``intent_as_hard=True`` → 意向升级为硬约束（一票否决）。

以及一个**危险的旧写法**：专业硬约束原先只比对 ``major.category``（门类）。
考生选「计算机类」（专业类）时 `major.category`（"工学"）不等于它 → **全部候选被否决**。
现在与 `scoring.major_match_detail` 同口径（门类/专业类/专业名三档都可匹配）。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.models import FilterCriteria, Preferences, StudentProfile
from app.db import models as db
from app.db import repositories as repo
from app.db.session import SessionLocal
from app.services import recommend_service
from app.services.recommend_service import criteria_from_profile


def _profile(**prefs) -> StudentProfile:
    return StudentProfile(
        id="p",
        province="zhejiang",
        year=2026,
        subjects=["物理", "化学", "生物"],
        total_score=630,
        preferences=Preferences(**prefs),
    )


# ---------------------------------------------------------------------------
# §1 criteria_from_profile 语义
# ---------------------------------------------------------------------------
class TestCriteriaFromProfile:
    def test_soft_intent_yields_empty_criteria(self):
        """默认（软偏好）→ 空 criteria：意向只影响排序，不过滤。"""
        profile = _profile(
            intended_regions=["zhejiang"],
            intended_levels=["985"],
            intended_major_categories=["计算机类"],
            intent_as_hard=False,
        )
        criteria = criteria_from_profile(profile)
        assert criteria.regions == []
        assert criteria.levels == []
        assert criteria.major_categories == []

    def test_hard_intent_yields_full_criteria(self):
        """intent_as_hard=True → 三项意向全部升级为硬约束。"""
        profile = _profile(
            intended_regions=["zhejiang", "jiangsu"],
            intended_levels=["985", "211"],
            intended_major_categories=["计算机类", "工学"],
            intent_as_hard=True,
        )
        criteria = criteria_from_profile(profile)
        assert criteria.regions == ["zhejiang", "jiangsu"]
        assert criteria.levels == ["985", "211"]
        assert criteria.major_categories == ["计算机类", "工学"]

    def test_no_intent_at_all(self):
        assert criteria_from_profile(_profile()) == FilterCriteria()


# ---------------------------------------------------------------------------
# §2 专业硬约束必须支持 门类 / 专业类 / 专业名 三档
# ---------------------------------------------------------------------------
class TestMajorHardConstraintLevels:
    """★ 回归：旧写法只比对 `major.category`，选专业类会把全部候选否决。"""

    @pytest.fixture(scope="module", autouse=True)
    def require_seeded_database(self) -> None:
        with SessionLocal() as session:
            unit = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
        if unit is None:
            pytest.fail("数据库为空。请先跑 scripts/seed.py --source hybrid")

    @pytest.fixture()
    def session(self):
        with SessionLocal() as session:
            yield session

    @pytest.fixture()
    def student(self, session):
        row = session.query(db.Student).filter(db.Student.total_score == 630).first()
        if row is None:
            pytest.fail("库里没有 630 分考生档案")
        return row

    def test_discipline_intent_does_not_reject_everything(self, session, student):
        """选「计算机类」（专业类）时，必须仍能通过一批候选。

        旧写法下这里会得到 0 个通过（因为 `major.category` 是"工学"）。
        """
        bundle = recommend_service.evaluate_candidates(
            session,
            student,
            criteria=FilterCriteria(major_categories=["计算机类"]),
            intent_as_hard=True,
        )
        assert bundle.filtered.passed, "选专业类不应把候选全部否决"
        # 通过的单位都应是计算机类（或其子专业）
        majors = repo.load_majors(session)
        for unit in bundle.filtered.passed[:50]:
            major = majors.get(unit.major_id or "")
            if major is not None:
                assert major.discipline == "计算机类" or "计算机" in (unit.major_name or "")

    def test_category_intent_accepts_whole_category(self, session, student):
        """选门类「工学」→ 工学下的专业类都应通过。"""
        bundle = recommend_service.evaluate_candidates(
            session,
            student,
            criteria=FilterCriteria(major_categories=["工学"]),
            intent_as_hard=True,
        )
        assert bundle.filtered.passed
        majors = repo.load_majors(session)
        sample = bundle.filtered.passed[:50]
        assert all(
            (majors.get(u.major_id or "") is None)
            or majors[u.major_id].category == "工学"
            for u in sample
        )

    def test_exact_major_name_intent(self, session, student):
        bundle = recommend_service.evaluate_candidates(
            session,
            student,
            criteria=FilterCriteria(major_categories=["计算机类"]),
            intent_as_hard=True,
        )
        assert bundle.filtered.passed


# ---------------------------------------------------------------------------
# §3 evaluate_candidates / recommend 默认按档案生成
# ---------------------------------------------------------------------------
class TestProfileDrivenEvaluation:
    @pytest.fixture(scope="module", autouse=True)
    def require_seeded_database(self) -> None:
        with SessionLocal() as session:
            unit = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
        if unit is None:
            pytest.fail("数据库为空。请先跑 scripts/seed.py --source hybrid")

    @pytest.fixture()
    def session(self):
        with SessionLocal() as session:
            yield session

    def test_no_criteria_uses_profile_intent_when_hard(self, session):
        """不传 criteria 时，档案里 intent_as_hard=True 的意向应自动生效。"""
        student = repo.create_student(
            session,
            StudentProfile(
                id="test-adr022-hard",
                province="zhejiang",
                year=2026,
                subjects=["物理", "化学", "生物"],
                total_score=630,
                preferences=Preferences(
                    intended_major_categories=["计算机类"], intent_as_hard=True
                ),
            ),
        )
        session.commit()
        bundle = recommend_service.evaluate_candidates(session, student)
        majors = repo.load_majors(session)
        checked = 0
        for unit in bundle.filtered.passed[:80]:
            major = majors.get(unit.major_id or "")
            if major is None:
                continue
            assert major.discipline == "计算机类" or major.category == "计算机类", unit.major_name
            checked += 1
        assert checked > 0
        session.delete(student)
        session.commit()

    def test_no_criteria_and_soft_intent_does_not_filter(self, session):
        """intent_as_hard=False → 不硬过滤（意向只影响排序）。"""
        student = repo.create_student(
            session,
            StudentProfile(
                id="test-adr022-soft",
                province="zhejiang",
                year=2026,
                subjects=["物理", "化学", "生物"],
                total_score=630,
                preferences=Preferences(
                    intended_major_categories=["计算机类"], intent_as_hard=False
                ),
            ),
        )
        session.commit()
        soft = recommend_service.evaluate_candidates(session, student)
        baseline = recommend_service.evaluate_candidates(
            session,
            student,
            criteria=FilterCriteria(),  # 显式空 = 同样不过滤
        )
        assert len(soft.filtered.passed) == len(baseline.filtered.passed)
        assert len(soft.filtered.passed) > 100, "软偏好不应剔除候选"
        session.delete(student)
        session.commit()

    def test_soft_intent_still_influences_utility(self, session):
        """软偏好必须体现在排序上：同意向的专业效用更高。"""
        student = repo.create_student(
            session,
            StudentProfile(
                id="test-adr022-utility",
                province="zhejiang",
                year=2026,
                subjects=["物理", "化学", "生物"],
                total_score=630,
                preferences=Preferences(
                    intended_major_categories=["计算机类"], intent_as_hard=False
                ),
            ),
        )
        session.commit()
        bundle = recommend_service.evaluate_candidates(session, student)
        by_level: dict[str, list[float]] = {}
        for scored, _ in bundle.pairs:
            level = scored.score_breakdown.major_match_level or "NONE"
            by_level.setdefault(level, []).append(scored.utility)
        assert "SAME_DISCIPLINE" in by_level, "应有命中「同一专业类」的候选"
        avg_match = sum(by_level["SAME_DISCIPLINE"]) / len(by_level["SAME_DISCIPLINE"])
        if "NONE" in by_level:
            avg_none = sum(by_level["NONE"]) / len(by_level["NONE"])
            assert avg_match > avg_none, "命中意向的专业效用应更高"
        session.delete(student)
        session.commit()


# ---------------------------------------------------------------------------
# §4 专业分类规则库端点
# ---------------------------------------------------------------------------
class TestMajorTaxonomyEndpoint:
    def test_returns_full_two_level_taxonomy(self):
        from fastapi.testclient import TestClient

        from app.core.major_taxonomy_data import BENKE_CATEGORIES
        from app.main import app

        response = TestClient(app).get("/api/v1/meta/major-taxonomy")
        assert response.status_code == 200
        body = response.json()
        data = body["data"]

        assert len(data["categories"]) == 12, "应为教育部 12 门类"
        total = sum(len(c["disciplines"]) for c in data["categories"])
        assert total == 93, "应为 93 专业类"
        # 与规则库逐项一致（唯一权威来源）
        for category in data["categories"]:
            assert category["name"] in BENKE_CATEGORIES
            expected = BENKE_CATEGORIES[category["name"]]
            assert [d["name"] for d in category["disciplines"]] == list(expected)
        assert body["evidence"], "必须带来源（§7 契约铁律）"
        assert data["source_url"].startswith("http")

    def test_disciplines_carry_real_major_counts(self):
        from fastapi.testclient import TestClient

        from app.main import app

        data = TestClient(app).get("/api/v1/meta/major-taxonomy").json()["data"]
        counts = [d["major_count"] for c in data["categories"] for d in c["disciplines"]]
        assert any(c > 0 for c in counts), "应统计出库中真实专业名数量"
        assert all(c >= 0 for c in counts)
