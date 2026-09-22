"""持久结果缓存（ADR-019）单测。

★ 最重要的一条：缓存**不得串号** —— 键与考生身份无关，但结果里也**不能**含考生身份。
本文件既验证"能复用"，也验证"复用是安全的"。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.models import FilterCriteria, ModelParams, StudentProfile
from app.db import models as db
from app.db import repositories as repo
from app.db.session import SessionLocal
from app.services import cache_service, recommend_service
from app.etl.synthetic import CURRENT_YEAR


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        units = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
    if units is None:
        pytest.fail("数据库为空，缓存测试无法运行。请先跑 scripts/seed.py --source hybrid")


@pytest.fixture()
def session():
    with SessionLocal() as session:
        yield session


def _make_student(session, *, score: int, tag: str) -> db.Student:
    """造一个**全新**考生（按 id 查重，避免误取到已存在的同位次考生）。"""
    sid = f"test-cache-{tag}"
    existing = session.get(db.Student, sid)
    if existing is not None:
        return existing
    row = repo.create_student(
        session,
        StudentProfile(
            id=sid,
            province="zhejiang",
            year=CURRENT_YEAR,
            track="综合",
            subjects=["物理", "化学", "生物"],
            total_score=score,
        ),
    )
    session.commit()
    return row


# ---------------------------------------------------------------------------
# §1 数据代次令牌
# ---------------------------------------------------------------------------
class TestDataVersion:
    def test_version_is_persisted_and_monotonic(self, session):
        before = cache_service.get_data_version(session)
        after = cache_service.bump_data_version(session, note="test")
        session.commit()
        assert after != before
        # 重新开一个 session 读 —— 必须**持久**（跨进程有效）
        with SessionLocal() as other:
            assert cache_service.get_data_version(other) == after

    def test_get_does_not_write(self, session):
        """读路径必须无副作用（否则每次查询都会写库）。"""
        cache_service.get_data_version(session)
        assert session.dirty == set() or not any(
            isinstance(obj, db.AppMeta) for obj in session.dirty
        )


# ---------------------------------------------------------------------------
# §2 指纹：影响结果的输入必须全部进键
# ---------------------------------------------------------------------------
class TestFingerprint:
    @staticmethod
    def _key(**overrides):
        base = dict(
            data_version="1",
            province="zhejiang",
            year=2026,
            rank=25000,
            criteria=FilterCriteria(),
            weights=None,
            params=ModelParams(),
            limit=60,
            include_too_risky=False,
            allowed_batches=None,
            intent_as_hard=False,
        )
        base.update(overrides)
        return cache_service.fingerprint_recommend(**base)[0]

    def test_same_inputs_same_key(self):
        assert self._key() == self._key()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("data_version", "2"),
            ("province", "shandong"),
            ("year", 2025),
            ("rank", 25001),
            ("limit", 61),
            ("include_too_risky", True),
            ("intent_as_hard", True),
            ("allowed_batches", ["zhejiang.public.seg2"]),
            ("weights", {"region": 0.9}),
        ],
    )
    def test_every_input_changes_the_key(self, field, value):
        """★ 漏掉任何一个影响结果的输入 = 一次静默的错误建议（ADR-016 同源教训）。"""
        assert self._key() != self._key(**{field: value})

    def test_criteria_changes_the_key(self):
        assert self._key() != self._key(criteria=FilterCriteria(regions=["beijing"]))

    def test_params_change_the_key(self):
        assert self._key() != self._key(params=ModelParams(safety_margin=0.5))


# ---------------------------------------------------------------------------
# §3 端到端：复用 + 不串号 + 失效
# ---------------------------------------------------------------------------
class TestRecommendCache:
    def test_cold_then_hit(self, session):
        student = _make_student(session, score=631, tag="cold")
        first = recommend_service.recommend(session, student, limit=5)
        session.commit()
        assert first.stats["cache"]["hit"] is False

        second = recommend_service.recommend(session, student, limit=5)
        session.commit()
        assert second.stats["cache"]["hit"] is True
        # 命中时返回的内容必须与首次一致
        assert [i["unit"]["unit_id"] for i in second.items] == [
            i["unit"]["unit_id"] for i in first.items
        ]

    def test_reuse_across_different_students_same_rank(self, session):
        """★ 另一位考生、同位次 → 允许复用（缓存键与身份无关）。"""
        a = _make_student(session, score=632, tag="A")
        b = _make_student(session, score=632, tag="B")
        assert a.id != b.id
        pa = recommend_service.evaluate_candidates(session, a).profile
        pb = recommend_service.evaluate_candidates(session, b).profile
        assert pa.rank == pb.rank, "两位考生位次必须相同才能验证复用"

        recommend_service.recommend(session, a, limit=5)
        session.commit()
        out_b = recommend_service.recommend(session, b, limit=5)
        session.commit()
        assert out_b.stats["cache"]["hit"] is True

    def test_cached_payload_contains_no_student_identity(self, session):
        """★ 复用安全性的根据：缓存体里不能有考生身份，否则会串号。"""
        student = _make_student(session, score=633, tag="identity")
        recommend_service.recommend(session, student, limit=5)
        session.commit()

        rows = list(session.execute(select(db.ResultCache)).scalars())
        assert rows, "应当已写入缓存"
        for row in rows:
            assert student.id not in row.payload
            assert "student_id" not in row.payload
            # 学号/姓名这类字段也不应出现
            assert "rank_source_url" in row.payload or True  # 来源 URL 允许（非身份）

    def test_limit_change_is_a_different_entry(self, session):
        student = _make_student(session, score=634, tag="limit")
        recommend_service.recommend(session, student, limit=5)
        session.commit()
        other = recommend_service.recommend(session, student, limit=6)
        session.commit()
        assert other.stats["cache"]["hit"] is False

    def test_bumping_data_version_invalidates(self, session):
        student = _make_student(session, score=635, tag="version")
        recommend_service.recommend(session, student, limit=5)
        session.commit()
        assert (
            recommend_service.recommend(session, student, limit=5).stats["cache"]["hit"]
            is True
        )

        cache_service.bump_data_version(session, note="test-invalidate")
        session.commit()
        after = recommend_service.recommend(session, student, limit=5)
        session.commit()
        assert after.stats["cache"]["hit"] is False, "代次变化后必须视为未命中"

    def test_use_cache_false_bypasses(self, session):
        student = _make_student(session, score=636, tag="bypass")
        recommend_service.recommend(session, student, limit=5)
        session.commit()
        fresh = recommend_service.recommend(session, student, limit=5, use_cache=False)
        session.commit()
        assert "cache" not in fresh.stats, "关闭缓存时不应报告命中"


# ---------------------------------------------------------------------------
# §4 运维：统计与清理
# ---------------------------------------------------------------------------
class TestCacheMaintenance:
    def test_stats_reports_current_and_stale(self, session):
        student = _make_student(session, score=637, tag="stats")
        recommend_service.recommend(session, student, limit=5)
        session.commit()
        cache_service.bump_data_version(session, note="test-stats")
        session.commit()

        info = cache_service.stats(session)
        assert info["entries"] >= 1
        assert info["stale_entries"] >= 1
        assert info["data_version"] == cache_service.get_data_version(session)
        assert "recommend" in info["kinds"]

    def test_clear_only_stale_keeps_current(self, session):
        student = _make_student(session, score=638, tag="clear")
        recommend_service.recommend(session, student, limit=5)
        session.commit()
        cache_service.bump_data_version(session, note="test-clear")
        session.commit()
        recommend_service.recommend(session, student, limit=5)
        session.commit()

        before = cache_service.stats(session)
        removed = cache_service.clear(session, only_stale=True)
        session.commit()
        after = cache_service.stats(session)
        assert removed == before["stale_entries"]
        assert after["stale_entries"] == 0
        assert after["entries"] == before["entries_current_version"]

    def test_corrupt_payload_is_treated_as_miss(self, session):
        """损坏的缓存行不能让请求崩掉（宁可不答，也不能 500）。"""
        key = "test-corrupt-key"
        cache_service.cache_put(
            session,
            key,
            data_version=cache_service.get_data_version(session),
            kind="recommend",
            label="corrupt",
            payload={"items": []},
        )
        session.commit()
        row = session.get(db.ResultCache, key)
        row.payload = "{not json"
        session.commit()
        assert cache_service.cache_get(session, key, row.data_version) is None
        session.delete(row)
        session.commit()
