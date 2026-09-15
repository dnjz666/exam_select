"""确定性模拟数据生成器（M1）。

★ 合规声明（AGENTS.md §12 / DOMAIN_RULES.md §6）
- 院校名 / 专业名来自 `etl/catalog.py`（公开信息）；
- **所有分数、位次、招生计划、学费、保研率均为模拟值**：落库一律 ``is_synthetic=1``、
  ``verified=0``，``source_url`` 为 ``synthetic://`` 前缀的可审计标记；
- **严禁**用于真实志愿填报。

确定性（M1 完成定义）
- 单一种子 ``SEED`` 驱动 ``random.Random``；生成顺序完全由**排序后的名册与固定循环**决定，
  不依赖 dict/set 遍历顺序 → 相同 seed 必产出逐字节一致的数据（``SyntheticDataset.digest()`` 校验）。

注入的已知规律（供 M2 算法与回测验证，``injections`` 随数据集返回）
1. **大小年**：约 10% 单位的历史位次剧烈震荡（归一化后 cv > 0.15）；
2. **计划突增 / 突减**：约 8% 单位的 2025 计划相对 2024 变动 ±45%~60%；
3. **新增专业**：约 7% 的 2025 单位**没有任何历史行**（M2 走 Step 0 回退，禁编造概率）；
4. **小计划**：约 6% 单位计划数 < 5（触发 PLAN_TOO_SMALL + 降置信度）；
5. **征集志愿**：约 3% 历史行来自征集（``is_collected=1`` + ``data_quality=COLLECTED``）；
6. **派生位次**：约 12% 历史行为 ``DERIVED``（由最低分反查，M2 需 ×0.9 降权）。

分数口径：各省满分与"3+3"计分规则一致（上海 660、海南标准分 900、其余 750），
数值均为模拟。位次口径统一：**数值越小越靠前**（DOMAIN_RULES.md §2.1）。
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import NamedTuple

from app.core.rules import RULES, get_rule
from app.etl import catalog

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SEED: int = 20250915
CURRENT_YEAR: int = 2025
YEARS: tuple[int, ...] = (2023, 2024, 2025)
HISTORY_YEARS: tuple[int, ...] = (2023, 2024)
SOURCE_PREFIX = "synthetic://exam_select/etl/synthetic.py"

#: 注入概率（模拟数据的"已知规律"密度，见模块 docstring）
P_VOLATILE = 0.10
P_PLAN_SPIKE = 0.08
P_NEW_MAJOR = 0.07
P_SMALL_PLAN = 0.06
P_COLLECTED = 0.03
P_DERIVED = 0.12

#: 每个省参与模拟的院校上限（本地全部 + 全国强校 + 外省抽样）
MAX_COLLEGES_PER_PROVINCE = 110
OUT_OF_PROVINCE_SAMPLE = 14


class ProvinceProfile(NamedTuple):
    """省份画像：考生规模（模拟，量级贴近真实）+ 分数分布参数（模拟）。"""

    candidates_2023: int
    annual_growth: float
    score_mean: float
    score_sd: float
    score_tail_mult: float
    score_high: int
    score_low: int


#: 六省市画像。考生规模量级参照真实公告的**数量级**（数值本身为模拟值）。
PROVINCE_PROFILES: dict[str, ProvinceProfile] = {
    "zhejiang": ProvinceProfile(390_000, 0.020, 500, 82, 1.30, 750, 260),
    "shandong": ProvinceProfile(700_000, 0.030, 470, 85, 1.32, 750, 240),
    "shanghai": ProvinceProfile(54_000, 0.030, 505, 78, 1.25, 660, 200),
    "beijing": ProvinceProfile(67_000, 0.050, 520, 80, 1.28, 750, 240),
    "tianjin": ProvinceProfile(70_000, 0.020, 500, 82, 1.30, 750, 250),
    "hainan": ProvinceProfile(74_000, 0.040, 480, 85, 1.30, 900, 300),
}

#: 层次 → 计划数区间（模拟）
_TIER_PLAN_BAND: dict[str, tuple[int, int]] = {
    "985": (20, 80),
    "211": (15, 60),
    "SY": (10, 50),
    "PROV": (8, 40),
    "PRIV": (10, 60),
}
#: 层次 → 学费区间（元/年，模拟）；民办/中外合作显著更高（名师铁律 10 必须在卡片明示）
_TUITION_PUBLIC = (4500, 7500)
_TUITION_PRIVATE = (18_000, 65_000)
_TUITION_SPECIAL = (8_000, 15_000)  # 医药 / 艺术类公办专业上浮


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _source() -> str:
    return f"{SOURCE_PREFIX}?seed={SEED}"


def _norm_cdf(z: float) -> float:
    """标准正态 CDF：Φ(z) = 0.5·erfc(-z/√2)。"""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _upper_tail(z: float) -> float:
    """P(X ≥ z) = 1 - Φ(z)。"""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _score_for_rank(table: list[tuple[int, int]], rank: int) -> int:
    """按一分一段表把位次线性插值回分数（``table`` = [(score, cumulative_rank)] 按分数降序）。"""
    if rank <= table[0][1]:
        return table[0][0]
    if rank >= table[-1][1]:
        return table[-1][0]
    for i in range(1, len(table)):
        lo_cum, hi_cum = table[i - 1][1], table[i][1]
        if hi_cum >= rank:
            if hi_cum == lo_cum:
                return table[i][0]
            ratio = (rank - lo_cum) / (hi_cum - lo_cum)
            return int(round(table[i - 1][0] + ratio * (table[i][0] - table[i - 1][0])))
    return table[-1][0]


def _is_hot(major_name: str) -> bool:
    return any(k in major_name for k in catalog.HOT_MAJOR_KEYWORDS)


def _is_cold(major_name: str) -> bool:
    return any(k in major_name for k in catalog.COLD_MAJOR_KEYWORDS)


# ---------------------------------------------------------------------------
# 数据集
# ---------------------------------------------------------------------------
@dataclass
class SyntheticDataset:
    """一次生成的完整模拟数据集（列表元素即待入库的行字典）。"""

    colleges: list[dict] = field(default_factory=list)
    majors: list[dict] = field(default_factory=list)
    score_rank_table: list[dict] = field(default_factory=list)
    province_year_stats: list[dict] = field(default_factory=list)
    admission_units: list[dict] = field(default_factory=list)
    admission_plans: list[dict] = field(default_factory=list)
    admission_history: list[dict] = field(default_factory=list)
    #: 注入样本清单（unit_key 列表），供 M2 回测与 tests 断言使用
    injections: dict[str, list[str]] = field(default_factory=dict)
    seed: int = SEED

    _TABLES = (
        "colleges",
        "majors",
        "score_rank_table",
        "province_year_stats",
        "admission_units",
        "admission_plans",
        "admission_history",
    )

    def counts(self) -> dict[str, int]:
        return {name: len(getattr(self, name)) for name in self._TABLES}

    def digest(self) -> str:
        """全表内容摘要：相同 seed 必须得到相同摘要（幂等与确定性验收）。"""
        h = hashlib.sha256()
        for name in self._TABLES:
            rows = sorted(getattr(self, name), key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
            h.update(f"##{name}\n".encode())
            for row in rows:
                h.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
                h.update(b"\n")
        return h.hexdigest()


# ---------------------------------------------------------------------------
# 生成：院校 / 专业
# ---------------------------------------------------------------------------
def _generate_colleges(rng: random.Random) -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    index: dict[str, dict] = {}
    # ★ 院校代码必须**全局唯一**：unit_key = f"{招生省}-{college_code}-{group_code}-{major_code}"，
    #   而同一招生省包含来自多省的院校；若代码按院校所在省各自编号，不同省院校会撞出相同 unit_key。
    for seq, college in enumerate(catalog.iter_colleges(), start=1):
        code = f"{1000 + seq:04d}"
        college_id = f"{college.province}-{code}"

        if college.tier == "985":
            postgrad = round(rng.uniform(0.25, 0.60), 3)
            masters, doctors = rng.randint(40, 60), rng.randint(30, 50)
        elif college.tier == "211":
            postgrad = round(rng.uniform(0.10, 0.30), 3)
            masters, doctors = rng.randint(25, 45), rng.randint(10, 30)
        elif college.tier == "SY":
            postgrad = round(rng.uniform(0.06, 0.20), 3)
            masters, doctors = rng.randint(18, 30), rng.randint(5, 20)
        elif college.tier == "PROV":
            postgrad = round(rng.uniform(0.01, 0.10), 3)
            masters, doctors = rng.randint(5, 20), rng.randint(0, 8)
        else:  # PRIV
            postgrad = round(rng.uniform(0.0, 0.03), 3)
            masters, doctors = rng.randint(0, 5), 0

        row = {
            "id": college_id,
            "code": code,
            "name": college.name,
            "province": college.province,
            "city": college.city,
            "level_tags": json.dumps(list(catalog.TIER_TAGS[college.tier]), ensure_ascii=False),
            "college_type": college.college_type,
            "affiliation": "教育部" if college.tier == "985" else ("省属" if college.tier != "PRIV" else "民办"),
            "is_public": catalog.TIER_IS_PUBLIC[college.tier],
            "postgrad_rate": postgrad,
            "master_points": masters,
            "doctor_points": doctors,
            "source_url": _source(),
            "is_synthetic": True,
            "_tier": college.tier,  # 生成期辅助字段（入库前剔除）
        }
        rows.append(row)
        index[college_id] = row
    return rows, index


def _generate_majors(rng: random.Random) -> tuple[list[dict], dict[str, dict]]:
    rows: list[dict] = []
    index: dict[str, dict] = {}
    for seq, major in enumerate(catalog.iter_majors(), start=1):
        code = f"{100000 + seq:06d}"
        row = {
            "id": f"{major.category}-{code}",
            "code": code,
            "name": major.name,
            "category": major.category,
            "discipline": major.discipline,
            "degree": "艺术学" if major.category == "艺术学" else ("医学" if major.category == "医学" else "学士"),
            "duration": 5 if major.discipline in ("临床医学类", "口腔医学类", "中医学类", "建筑类") else 4,
            "subject_eval_grade": rng.choice(["A+", "A", "A-", "B+", "B", "B-", "C+", None]),
            "source_url": _source(),
            "is_synthetic": True,
            "_mode": major.subject_mode,  # 生成期辅助字段（入库前剔除）
            "_subjects": list(major.subjects),
        }
        rows.append(row)
        index[row["id"]] = row
    return rows, index


# ---------------------------------------------------------------------------
# 生成：一分一段表与年度元数据
# ---------------------------------------------------------------------------
def _generate_score_tables() -> tuple[list[dict], list[dict], dict[tuple[str, int], list[tuple[int, int]]]]:
    rows: list[dict] = []
    stats: list[dict] = []
    lookups: dict[tuple[str, int], list[tuple[int, int]]] = {}

    for province in sorted(PROVINCE_PROFILES):
        profile = PROVINCE_PROFILES[province]
        for offset, year in enumerate(YEARS):
            total = int(round(profile.candidates_2023 * (1 + profile.annual_growth) ** offset))
            stats.append(
                {
                    "province": province,
                    "year": year,
                    "track": "综合",
                    "total_candidates": total,
                    "source_url": _source(),
                    "is_synthetic": True,
                }
            )

            table: list[tuple[int, int]] = []
            prev_cum = 0
            for score in range(profile.score_high, profile.score_low - 1, -1):
                u = (score - profile.score_mean) / profile.score_sd
                z = u if u >= 0 else u / profile.score_tail_mult  # 下尾加长，贴近真实分布
                cum = int(round(total * _upper_tail(z)))
                cum = max(prev_cum, min(total, cum))
                if not table:  # 最高分至少 1 人
                    cum = max(1, cum)
                    prev_cum = 0
                table.append((score, cum))
                rows.append(
                    {
                        "province": province,
                        "year": year,
                        "track": "综合",
                        "score": score,
                        "count_at_score": cum - prev_cum,
                        "cumulative_rank": cum,
                        "source_url": _source(),
                        "is_synthetic": True,
                    }
                )
                prev_cum = cum

            # 最低分处累计位次 == 总考生数（位次归一化分母必须闭合）
            if table:
                last = table.pop()
                rows[-1]["cumulative_rank"] = total
                rows[-1]["count_at_score"] = total - (table[-1][1] if table else 0)
                table.append((last[0], total))
            lookups[(province, year)] = table
    return rows, stats, lookups


# ---------------------------------------------------------------------------
# 生成：投档单位 / 计划 / 历史
# ---------------------------------------------------------------------------
def _candidate_colleges(province: str, college_index: dict[str, dict], rng: random.Random) -> list[dict]:
    local = [c for c in college_index.values() if c["province"] == province]
    strong = [
        c
        for c in college_index.values()
        if c["province"] != province and c["_tier"] in ("985", "211", "SY")
    ]
    weak = [
        c
        for c in college_index.values()
        if c["province"] != province and c["_tier"] in ("PROV", "PRIV")
    ]
    weak.sort(key=lambda c: c["id"])
    sampled = rng.sample(weak, min(OUT_OF_PROVINCE_SAMPLE, len(weak)))
    chosen = sorted({c["id"]: c for c in (local + strong + sampled)}.values(), key=lambda c: c["id"])
    return chosen[:MAX_COLLEGES_PER_PROVINCE]


def _pick_tuition(tier: str, category: str, rng: random.Random) -> int:
    if tier == "PRIV":
        lo, hi = _TUITION_PRIVATE
    elif category in ("医学", "艺术学"):
        lo, hi = _TUITION_SPECIAL
    else:
        lo, hi = _TUITION_PUBLIC
    step = 1000 if hi >= 10_000 else 100
    return int(round(rng.randint(lo, hi) / step) * step)


def _generate_units(
    college_index: dict[str, dict],
    major_index: dict[str, dict],
    lookups: dict[tuple[str, int], list[tuple[int, int]]],
    stats_index: dict[tuple[str, int], int],
    rng: random.Random,
) -> tuple[list[dict], list[dict], list[dict], dict[str, list[str]]]:
    units: list[dict] = []
    plans: list[dict] = []
    history: list[dict] = []
    injections: dict[str, list[str]] = {
        "volatile": [],
        "plan_spike": [],
        "new_major": [],
        "small_plan": [],
        "collected": [],
        "derived": [],
    }
    majors_sorted = sorted(major_index.values(), key=lambda m: m["id"])

    for province in sorted(RULES):
        rule = get_rule(province)
        batch = rule.main_batch()
        profile = PROVINCE_PROFILES[province]
        total_current = stats_index[(province, CURRENT_YEAR)]
        candidates = _candidate_colleges(province, college_index, rng)

        for college in candidates:
            tier = college["_tier"]
            n_majors = rng.randint(4, 10)
            picked = sorted(
                rng.sample(majors_sorted, min(n_majors, len(majors_sorted))), key=lambda m: m["id"]
            )

            # 选考要求相同的专业打包成组（院校专业组模式的真实打包逻辑）
            groups: dict[tuple[str, tuple[str, ...]], list[dict]] = {}
            for major in picked:
                key = (major["_mode"], tuple(major["_subjects"]))
                if batch.majors_per_group is not None:
                    bucket = groups.setdefault(key, [])
                    if len(bucket) >= batch.majors_per_group:
                        continue  # 组内专业数上限（上海 4 / 北京 6 / 海南 6）
                    bucket.append(major)
                else:
                    groups.setdefault(key, []).append(major)

            group_seq = 0
            for key in sorted(groups, key=lambda k: (k[0], k[1])):
                majors_in_group = groups[key]
                if not majors_in_group:
                    continue
                group_seq += 1
                if batch.unit_type.value == "MAJOR_GROUP":
                    group_code = f"{college['code']}-G{group_seq}"
                    group_name = f"第{group_seq}组（{'、'.join(key[1]) or '不限'}）"
                else:
                    group_code = None
                    group_name = None

                for major in majors_in_group:
                    unit_key = f"{province}-{college['code']}-{group_code or 'NA'}-{major['code']}"
                    unit_id = f"{province}-{CURRENT_YEAR}-{college['code']}-{group_code or 'NA'}-{major['code']}"

                    # ---- 计划数（含小计划与突增注入）
                    lo, hi = _TIER_PLAN_BAND[tier]
                    base_plan = rng.randint(lo, hi)
                    plan_2024 = max(1, int(round(base_plan * rng.uniform(0.9, 1.1))))
                    spike = rng.random() < P_PLAN_SPIKE
                    if spike:
                        factor = rng.choice([-0.55, -0.45, 0.45, 0.60])
                        plan_2025 = max(1, int(round(plan_2024 * (1 + factor))))
                    else:
                        plan_2025 = max(1, int(round(base_plan * rng.uniform(0.9, 1.1))))
                    small = rng.random() < P_SMALL_PLAN
                    if small:
                        plan_2025 = rng.randint(2, 4)
                        plan_2024 = max(1, plan_2025 + rng.randint(-1, 1))

                    category = major["category"]
                    units.append(
                        {
                            "unit_id": unit_id,
                            "unit_type": batch.unit_type.value,
                            "province": province,
                            "year": CURRENT_YEAR,
                            "batch": batch.batch_code,
                            "college_id": college["id"],
                            "group_code": group_code,
                            "group_name": group_name,
                            "major_id": major["id"],
                            "major_name": major["name"],
                            "subject_requirement": json.dumps(
                                {"mode": key[0], "subjects": list(key[1])}, ensure_ascii=False
                            ),
                            "subject_req_status": "PARSED",
                            "plan_count": plan_2025,
                            "tuition": _pick_tuition(tier, category, rng),
                            "duration": major["duration"],
                            "campus": college["city"],
                            "remarks": "模拟数据；院校专业组内服从调剂" if batch.has_major_adjustment else "模拟数据",
                            "is_synthetic": True,
                            "source_url": _source(),
                            "_plan_2024": plan_2024,  # 生成期辅助字段（入库前剔除）
                        }
                    )
                    if spike:
                        injections["plan_spike"].append(unit_key)
                    if small:
                        injections["small_plan"].append(unit_key)

                    # ---- 计划快照（逐年）
                    plan_by_year: dict[int, int] = {}
                    for year in YEARS:
                        if year == CURRENT_YEAR:
                            value = plan_2025
                        elif year == 2024:
                            value = plan_2024
                        else:
                            value = max(1, int(round(plan_2024 * rng.uniform(0.9, 1.1))))
                        plan_by_year[year] = value
                        plans.append(
                            {
                                "unit_key": unit_key,
                                "year": year,
                                "plan_count": value,
                                "is_synthetic": True,
                                "source_url": _source(),
                            }
                        )

                    # ---- 新增专业：无任何历史行（M2 必须走 Step 0 回退，禁编造）
                    if rng.random() < P_NEW_MAJOR:
                        injections["new_major"].append(unit_key)
                        continue

                    # ---- 历史位次（含大小年注入）
                    frac = rng.uniform(*catalog.TIER_RANK_BAND[tier])
                    if _is_hot(major["name"]):
                        frac *= 0.62
                    elif _is_cold(major["name"]):
                        frac *= 1.45
                    frac = min(frac, 0.95)
                    volatile = rng.random() < P_VOLATILE
                    if volatile:
                        injections["volatile"].append(unit_key)
                        # 大小年方向：随机指定哪一年是"冷年"（位次异常靠后），
                        # 两年必须一大一小，否则只是单向下滑而非震荡
                        cold_year = rng.choice(list(HISTORY_YEARS))

                    for year in HISTORY_YEARS:
                        total_year = stats_index[(province, year)]
                        rank_base = frac * total_year
                        if volatile:
                            mult = (
                                rng.uniform(1.25, 1.45)
                                if year == cold_year
                                else rng.uniform(0.70, 0.80)
                            )
                        else:
                            mult = rng.uniform(0.94, 1.06)
                        min_rank = max(1, int(round(rank_base * mult)))

                        collected = rng.random() < P_COLLECTED
                        if collected:
                            min_rank = max(1, int(round(min_rank * rng.uniform(1.10, 1.35))))
                            quality = "COLLECTED"
                        else:
                            quality = "DERIVED" if rng.random() < P_DERIVED else "OK"
                        # ★ 位次不可能大于该年考生总数（大小年 × 征集 × 冷门叠乘会越界）
                        min_rank = max(1, min(min_rank, total_year))
                        if quality == "DERIVED":
                            injections["derived"].append(f"{unit_key}@{year}")
                        if collected:
                            injections["collected"].append(f"{unit_key}@{year}")

                        min_score = _score_for_rank(lookups[(province, year)], min_rank)
                        avg_rank = max(1, int(round(min_rank * rng.uniform(0.90, 0.98))))
                        history.append(
                            {
                                "unit_key": unit_key,
                                "province": province,
                                "year": year,
                                "batch": batch.batch_code,
                                "unit_type": batch.unit_type.value,
                                "college_id": college["id"],
                                "group_code": group_code,
                                "major_id": major["id"],
                                "min_score": min_score,
                                "min_rank": min_rank,
                                "avg_score": _score_for_rank(lookups[(province, year)], avg_rank),
                                "avg_rank": avg_rank,
                                "plan_count": plan_by_year[year],
                                "admitted_count": max(
                                    1, int(round(plan_by_year[year] * rng.uniform(0.95, 1.02)))
                                ),
                                "is_collected": collected,
                                "data_quality": quality,
                                "total_candidates": total_year,
                                "is_synthetic": True,
                                "source_url": _source(),
                                "verified": False,
                            }
                        )
    return units, plans, history, injections


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def generate(seed: int = SEED) -> SyntheticDataset:
    """生成完整模拟数据集（确定性：同 seed → 同 digest）。"""
    unknown = set(PROVINCE_PROFILES) - set(RULES)
    if unknown:
        raise ValueError(f"省份画像与规则包不一致：{sorted(unknown)} 无规则包")

    rng = random.Random(seed)
    colleges, college_index = _generate_colleges(rng)
    majors, major_index = _generate_majors(rng)
    score_rows, stat_rows, lookups = _generate_score_tables()
    stats_index = {(row["province"], row["year"]): row["total_candidates"] for row in stat_rows}
    units, plans, history, injections = _generate_units(
        college_index, major_index, lookups, stats_index, rng
    )

    dataset = SyntheticDataset(
        colleges=[{k: v for k, v in row.items() if not k.startswith("_")} for row in colleges],
        majors=[{k: v for k, v in row.items() if not k.startswith("_")} for row in majors],
        score_rank_table=score_rows,
        province_year_stats=stat_rows,
        admission_units=[{k: v for k, v in row.items() if not k.startswith("_")} for row in units],
        admission_plans=plans,
        admission_history=history,
        injections={k: sorted(set(v)) for k, v in injections.items()},
        seed=seed,
    )
    return dataset
