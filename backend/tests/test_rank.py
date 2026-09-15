"""分数 ↔ 位次换算测试（AGENTS.md §6.1）。"""

from __future__ import annotations

import pytest

from app.core.rank import (
    InsufficientRankData,
    RankTable,
    build_rank_table,
    equivalent_score,
    normalize_rank,
    rank_percentile,
    rank_to_score,
    score_to_rank,
)

from factories import make_table_rows


@pytest.fixture()
def table() -> RankTable:
    return build_rank_table(make_table_rows(), total_candidates=400_000)


def test_build_from_rows_and_properties(table: RankTable) -> None:
    assert table.province == "zhejiang"
    assert table.max_score == 700
    assert table.min_score == 500
    assert table.total_candidates == 400_000
    assert len(table.scores) == len(table.cumulative)


def test_build_rank_table_rejects_bad_input() -> None:
    with pytest.raises(InsufficientRankData):
        build_rank_table([])
    with pytest.raises(ValueError):
        # 多家省份混在一起：无法确定口径
        build_rank_table(make_table_rows() + make_table_rows(province="beijing"))
    rows = make_table_rows()
    rows[0]["score"] = 500  # 破坏严格降序
    with pytest.raises(ValueError):
        build_rank_table(rows)
    rows = make_table_rows()
    rows[1]["cumulative_rank"] = 0  # 破坏非递减
    with pytest.raises(ValueError):
        build_rank_table(rows)
    with pytest.raises(ValueError):
        build_rank_table(make_table_rows(), total_candidates=0)


def test_build_rank_table_accepts_objects() -> None:
    class Row:
        def __init__(self, data: dict) -> None:
            self.__dict__.update(data)

    rows = [Row(row) for row in make_table_rows()]
    table = build_rank_table(rows)
    assert table.total_candidates == 400_000  # 缺省取最低分累计位次


def test_score_to_rank_exact_interpolate_and_boundaries(table: RankTable) -> None:
    # 精确命中
    assert score_to_rank(table, 700) == 1
    assert score_to_rank(table, 600) == table.cumulative[table.scores.index(600)]
    # 高于最高分 → 1；低于最低分 → 总考生数
    assert score_to_rank(table, 750) == 1
    assert score_to_rank(table, 400) == 400_000
    # 单调性：分数越低，位次越大
    ranks = [score_to_rank(table, score) for score in range(700, 499, -5)]
    assert ranks == sorted(ranks)
    # 插值落在相邻档之间（表是整数分，这里用两档中点检验平滑性）
    mid = score_to_rank(table, 699)
    assert 1 <= mid <= score_to_rank(table, 698)


def test_rank_to_score_inverse_and_boundaries(table: RankTable) -> None:
    assert rank_to_score(table, 1) == 700
    assert rank_to_score(table, 400_000) == 500
    assert rank_to_score(table, 10**9) == 500
    # 往返一致性：一分一段表是**整数分**，一个分数档覆盖多个位次，
    # 因此往返误差上限是"每档覆盖的位次数"（≈ total / 档数），而不是 1。
    ranks_per_point = table.total_candidates / len(table.scores)
    for rank in (1, 1000, 50_000, 200_000, 399_999):
        score = rank_to_score(table, rank)
        assert abs(score_to_rank(table, score) - rank) <= ranks_per_point + 1
    # 方向性：位次越小 → 分数越高（不允许写反）
    assert rank_to_score(table, 1000) > rank_to_score(table, 200_000)
    assert score_to_rank(table, 690) < score_to_rank(table, 600)


def test_normalize_rank_direction() -> None:
    # 今年考生更多 → 同样的位次含金量下降 → 归一化后数值变大
    assert normalize_rank(10000, 400_000, 440_000) == pytest.approx(11000.0)
    assert normalize_rank(10000, 400_000, 360_000) == pytest.approx(9000.0)
    with pytest.raises(ValueError):
        normalize_rank(10000, 0, 400_000)


def test_rank_percentile_and_equivalent_score(table: RankTable) -> None:
    assert rank_percentile(1000, 400_000) == pytest.approx(0.0025)
    assert rank_percentile(0, 400_000) == 0.0
    assert rank_percentile(400_000, 400_000) == 1.0
    with pytest.raises(ValueError):
        rank_percentile(1, 0)
    other = build_rank_table(make_table_rows(year=2025), total_candidates=380_000)
    assert equivalent_score(table, other, 1000) == rank_to_score(other, 1000)
