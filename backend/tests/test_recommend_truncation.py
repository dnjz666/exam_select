"""推荐列表"按分层取样"的测试（ADR-020 / M7）。

## 被修的缺陷

原实现是「按 ``(tier, -utility)`` 排序后取前 N」，而 ``TIER_ORDER`` 把 CHONG 排最前，
于是 ``limit`` 小于 CHONG 候选数时**整页全是"冲"**。实测（浙江 630 分）：

    limit=  8 → {'CHONG': 8}
    limit= 20 → {'CHONG': 20}
    limit= 60 → {'CHONG': 60}      ← 全池明明有 BAO 62 / DIAN 7824

考生会以为"一个稳的都没有"，这是**误导性展示**。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.models import ModelParams, Tier
from app.db import models as db
from app.db.session import SessionLocal
from app.services.recommend_service import TIER_ORDER, allocate_display_slots, recommend

#: 与 ModelParams.quota 一致的默认权重（冲 37.5 / 稳 37.5 / 保 18.75 / 垫 6.25）
WEIGHTS = dict(ModelParams().quota)


def _pools(**counts: int) -> dict[Tier, list[int]]:
    return {
        Tier.CHONG: list(range(counts.get("CHONG", 0))),
        Tier.WEN: list(range(counts.get("WEN", 0))),
        Tier.BAO: list(range(counts.get("BAO", 0))),
        Tier.DIAN: list(range(counts.get("DIAN", 0))),
        Tier.TOO_RISKY: list(range(counts.get("TOO_RISKY", 0))),
    }


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        unit = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
    if unit is None:
        pytest.fail("数据库为空。请先跑 scripts/seed.py --source hybrid")


@pytest.fixture()
def session():
    with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# §1 纯函数：分配算法
# ---------------------------------------------------------------------------
class TestAllocateDisplaySlots:
    def test_proportional_when_all_pools_are_deep(self):
        pools = _pools(CHONG=1000, WEN=1000, BAO=1000, DIAN=1000)
        allocation, shortfall = allocate_display_slots(
            pools, 80, WEIGHTS, include_too_risky=False
        )
        assert sum(allocation.values()) == 80
        # 与 §6.3 配额一致：浙江 80 → 冲30/稳30/保15/垫5
        assert allocation[Tier.CHONG] == 30
        assert allocation[Tier.WEN] == 30
        assert allocation[Tier.BAO] == 15
        assert allocation[Tier.DIAN] == 5
        assert all(v == 0 for v in shortfall.values())

    def test_never_returns_all_chong_even_for_tiny_limit(self):
        """★ 核心回归：小 limit 也必须是混合档，不能整页"冲"。"""
        pools = _pools(CHONG=1000, WEN=1000, BAO=1000, DIAN=1000)
        allocation, _ = allocate_display_slots(pools, 8, WEIGHTS, include_too_risky=False)
        assert allocation[Tier.CHONG] < 8, "8 个展示位不能全给冲档"
        assert allocation[Tier.WEN] > 0
        assert allocation[Tier.BAO] + allocation[Tier.DIAN] > 0

    def test_redistributes_when_a_tier_is_empty(self):
        """保/垫候选为空时，其份额转给仍有余量的层，不浪费展示位。"""
        pools = _pools(CHONG=1000, WEN=1000)  # 无 BAO / DIAN
        allocation, shortfall = allocate_display_slots(
            pools, 40, WEIGHTS, include_too_risky=False
        )
        assert sum(allocation.values()) == 40, "空档的份额必须被再分配，不能留下空位"
        assert allocation[Tier.BAO] == 0 and allocation[Tier.DIAN] == 0
        assert shortfall[Tier.BAO] > 0 and shortfall[Tier.DIAN] > 0, "缺口要如实报告"

    def test_never_exceeds_pool_capacity(self):
        pools = _pools(CHONG=2, WEN=3, BAO=1, DIAN=0)
        allocation, _ = allocate_display_slots(pools, 100, WEIGHTS, include_too_risky=False)
        assert allocation[Tier.CHONG] == 2
        assert allocation[Tier.WEN] == 3
        assert allocation[Tier.BAO] == 1
        assert allocation[Tier.DIAN] == 0
        assert sum(allocation.values()) == 6, "取空即止，绝不用低质量候选凑数"

    def test_too_risky_only_gets_leftovers_when_explicitly_enabled(self):
        pools = _pools(CHONG=1, WEN=1, BAO=1, DIAN=1, TOO_RISKY=50)
        off, _ = allocate_display_slots(pools, 10, WEIGHTS, include_too_risky=False)
        assert off[Tier.TOO_RISKY] == 0, "默认不得把过险档塞给考生"
        on, _ = allocate_display_slots(pools, 10, WEIGHTS, include_too_risky=True)
        assert on[Tier.TOO_RISKY] > 0, "显式开启后余量才给过险档"
        assert sum(on.values()) == 10

    def test_shortfall_measures_entitlement_not_allocation(self):
        """缺口 = 配额应得 − 候选数（这才是"保底缺失"的判据）。"""
        pools = _pools(CHONG=1000, WEN=1000, BAO=0, DIAN=1000)
        allocation, shortfall = allocate_display_slots(
            pools, 80, WEIGHTS, include_too_risky=False
        )
        # 80 × 0.1875 = 15 → 保底应得 15，实际 0
        assert shortfall[Tier.BAO] == 15
        assert shortfall[Tier.CHONG] == 0
        assert sum(allocation.values()) == 80

    def test_deterministic(self):
        pools = _pools(CHONG=37, WEN=41, BAO=13, DIAN=7)
        first = allocate_display_slots(pools, 50, WEIGHTS, include_too_risky=False)
        second = allocate_display_slots(pools, 50, WEIGHTS, include_too_risky=False)
        assert first == second

    def test_zero_and_negative_limit(self):
        pools = _pools(CHONG=10)
        for limit in (0, -1):
            allocation, shortfall = allocate_display_slots(
                pools, limit, WEIGHTS, include_too_risky=False
            )
            assert sum(allocation.values()) == 0
            assert set(allocation) == set(TIER_ORDER)
            assert set(shortfall) == set(TIER_ORDER)

    def test_all_pools_empty(self):
        allocation, shortfall = allocate_display_slots(
            _pools(), 20, WEIGHTS, include_too_risky=False
        )
        assert sum(allocation.values()) == 0
        assert shortfall[Tier.BAO] > 0

    def test_sequential_rule_has_no_weights(self):
        """顺序志愿批次没有配额 → 不按分层取样（返回全 0，由调用方决定）。"""
        allocation, _ = allocate_display_slots(
            _pools(CHONG=10, WEN=10), 10, {}, include_too_risky=False
        )
        assert sum(allocation.values()) == 0


# ---------------------------------------------------------------------------
# §2 端到端：真实 recommend
# ---------------------------------------------------------------------------
def _student(session, score: int) -> db.Student:
    row = session.query(db.Student).filter(db.Student.total_score == score).first()
    if row is None:
        pytest.fail(f"库里没有 {score} 分的考生档案")
    return row


class TestRecommendSampling:
    @pytest.mark.parametrize("limit", [8, 20, 60])
    def test_returned_list_is_mixed_not_all_chong(self, session, limit):
        """★ 核心回归：小 limit 下必须各档都有。"""
        student = _student(session, 630)
        out = recommend(session, student, limit=limit, use_cache=False)
        tiers = {item["tier"] for item in out.items}
        assert len(out.items) == limit
        assert tiers - {Tier.CHONG.value}, f"limit={limit} 只返回了冲档：{tiers}"
        assert len(tiers) >= 2, f"limit={limit} 只返回了一个分层：{tiers}"

    def test_returned_never_exceeds_limit(self, session):
        student = _student(session, 630)
        for limit in (1, 2, 5, 137):
            out = recommend(session, student, limit=limit, use_cache=False)
            assert len(out.items) <= limit

    def test_every_returned_item_still_has_evidence(self, session):
        """契约铁律 1：取样方式变了，证据链不能丢。"""
        student = _student(session, 630)
        out = recommend(session, student, limit=20, use_cache=False)
        assert out.items
        assert all(item["evidence"] for item in out.items)
        assert all(
            entry.get("source_url")
            for item in out.items
            for entry in item["evidence"]
        )

    def test_stats_expose_allocation_and_shortfall(self, session):
        student = _student(session, 630)
        out = recommend(session, student, limit=20, use_cache=False)
        assert "tier_allocation" in out.stats
        assert "tier_shortfall" in out.stats
        assert sum(out.stats["tier_allocation"].values()) == out.stats["returned"]

    def test_order_is_still_a_gradient(self, session):
        """最终顺序仍按 冲→稳→保→垫，方便前端按梯度阅读。"""
        student = _student(session, 630)
        out = recommend(session, student, limit=60, use_cache=False)
        indexes = [TIER_ORDER.index(Tier(item["tier"])) for item in out.items]
        assert indexes == sorted(indexes), "返回顺序必须保持分层梯度"

    def test_too_risky_not_returned_by_default(self, session):
        student = _student(session, 630)
        out = recommend(session, student, limit=60, use_cache=False)
        assert Tier.TOO_RISKY.value not in {i["tier"] for i in out.items}

    def test_sequential_batch_is_not_quota_sampled(self, session):
        """顺序志愿批次无配额 → 保持原"取前 N"行为（不套用平行志愿配额）。"""
        student = _student(session, 630)
        out = recommend(
            session,
            student,
            limit=5,
            allowed_batches=["zhejiang.advance.college"],
            use_cache=False,
        )
        # 顺序志愿批次在真实数据里没有单位 → 返回空即可，重点是**不能崩**
        assert isinstance(out.items, list)
