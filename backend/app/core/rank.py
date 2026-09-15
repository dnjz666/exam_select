"""分数 ↔ 位次换算与位次归一化（AGENTS.md §6.1）。

设计约束
--------
- **纯函数**：调用方（L4）把 ``score_rank_table`` 的行查好传进来；core 禁 IO（ADR-003）。
- **位次口径**：数值越小越靠前 = 越难考（DOMAIN_RULES.md §2.1），全模块统一。
- **缺数据必须报错**：一分一段表缺失时抛 :class:`InsufficientRankData`，
  绝不用估算值糊弄（AGENTS.md §8.1 红线）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class InsufficientRankData(ValueError):
    """一分一段表缺失/为空——位次换算不可用（必须显式提示考生，禁止估算）。"""


@dataclass(frozen=True)
class RankTable:
    """一分一段表的不可变视图（按分数降序）。"""

    province: str
    year: int
    track: str
    scores: tuple[int, ...]  # 降序
    cumulative: tuple[int, ...]  # 与 scores 对齐：#(score >= s)
    total_candidates: int

    def __post_init__(self) -> None:
        if not self.scores:
            raise InsufficientRankData(f"{self.province}/{self.year}/{self.track}: 一分一段表为空")
        if len(self.scores) != len(self.cumulative):
            raise ValueError("scores 与 cumulative 长度不一致")
        for i in range(1, len(self.scores)):
            if self.scores[i] >= self.scores[i - 1]:
                raise ValueError("scores 必须严格降序")
            if self.cumulative[i] < self.cumulative[i - 1]:
                raise ValueError("cumulative_rank 必须非递减")
        if self.total_candidates <= 0:
            raise ValueError("total_candidates 必须为正")

    # ---- 便捷属性 ----
    @property
    def max_score(self) -> int:
        return self.scores[0]

    @property
    def min_score(self) -> int:
        return self.scores[-1]

    def percentile(self, rank: int) -> float:
        """位次 → 百分位（越小越靠前）。"""
        return rank_percentile(rank, self.total_candidates)


def build_rank_table(
    rows: Iterable[Mapping[str, Any] | Any],
    *,
    total_candidates: int | None = None,
) -> RankTable:
    """由 ``score_rank_table`` 行（dict 或带属性的对象）构建 :class:`RankTable`。

    ``total_candidates`` 缺省时取最低分处的累计位次（一分一段表必须闭合到总考生数，
    由 ``etl/validate.py`` 强制）。
    """
    materialized: list[tuple[str, int, str, int, int]] = []
    for row in rows:
        get = row.get if isinstance(row, Mapping) else (lambda k, r=row: getattr(r, k))
        materialized.append(
            (
                get("province"),
                int(get("year")),
                get("track"),
                int(get("score")),
                int(get("cumulative_rank")),
            )
        )
    if not materialized:
        raise InsufficientRankData("score_rank_table 为空：位次换算不可用")

    provinces = {r[0] for r in materialized}
    years = {r[1] for r in materialized}
    tracks = {r[2] for r in materialized}
    if len(provinces) != 1 or len(years) != 1 or len(tracks) != 1:
        raise ValueError("build_rank_table 只接受单一 (province, year, track) 的行集合")

    materialized.sort(key=lambda r: -r[3])
    total = total_candidates if total_candidates is not None else materialized[-1][4]
    return RankTable(
        province=materialized[0][0],
        year=materialized[0][1],
        track=materialized[0][2],
        scores=tuple(r[3] for r in materialized),
        cumulative=tuple(r[4] for r in materialized),
        total_candidates=int(total),
    )


def score_to_rank(table: RankTable, score: int) -> int:
    """分数 → 位次（线性插值）。

    边界（§6.1）：高于最高分 → 1；低于最低分 → 总考生数。
    """
    scores, cumulative = table.scores, table.cumulative
    if score >= scores[0]:
        return 1
    if score <= scores[-1]:
        return table.total_candidates
    for i in range(1, len(scores)):
        hi_score, lo_score = scores[i - 1], scores[i]
        if lo_score <= score <= hi_score:
            hi_cum, lo_cum = cumulative[i - 1], cumulative[i]
            if hi_score == lo_score:
                return max(1, hi_cum)
            ratio = (hi_score - score) / (hi_score - lo_score)
            rank = hi_cum + ratio * (lo_cum - hi_cum)
            return max(1, min(table.total_candidates, int(round(rank))))
    return table.total_candidates  # pragma: no cover - 上面的区间必然覆盖


def rank_to_score(table: RankTable, rank: int) -> int:
    """位次 → 分数（线性插值；位次越小分数越高）。"""
    scores, cumulative = table.scores, table.cumulative
    if rank <= cumulative[0]:
        return scores[0]
    if rank >= table.total_candidates:
        return scores[-1]
    for i in range(1, len(cumulative)):
        lo_cum, hi_cum = cumulative[i - 1], cumulative[i]
        if lo_cum < rank <= hi_cum:
            if hi_cum == lo_cum:
                return scores[i]
            ratio = (rank - lo_cum) / (hi_cum - lo_cum)
            return int(round(scores[i - 1] + ratio * (scores[i] - scores[i - 1])))
    return scores[-1]  # pragma: no cover


def normalize_rank(rank: int, from_total: int, to_total: int) -> float:
    """位次归一化：``R_adj = R × (N_今年 / N_当年)``（§6.1，跨年可比的关键）。

    考生人数增加的年份，同样的位次含金量下降 → 归一化后位次数值变大。
    """
    if from_total <= 0 or to_total <= 0:
        raise ValueError("total_candidates 必须为正（位次归一化的分母）")
    return rank * (to_total / from_total)


def rank_percentile(rank: int, total_candidates: int) -> float:
    """位次 → 百分位（0~1，越小越靠前）。"""
    if total_candidates <= 0:
        raise ValueError("total_candidates 必须为正")
    return min(1.0, max(0.0, rank / total_candidates))


def equivalent_score(
    table_from: RankTable, table_to: RankTable, rank: int
) -> int:
    """等效分：把位次按另一年的表换算成该年的分数（便于家长理解，§8.1）。"""
    return rank_to_score(table_to, rank)


__all__ = [
    "InsufficientRankData",
    "RankTable",
    "build_rank_table",
    "equivalent_score",
    "normalize_rank",
    "rank_percentile",
    "rank_to_score",
    "score_to_rank",
]

# 便于类型检查器理解 Sequence 用法（仅用于签名文档）
_ = Sequence
