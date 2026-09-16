"""数据质量校验（M1）。

用法::

    backend\\.venv\\Scripts\\python.exe -m app.etl.validate --report

设计
----
- 校验函数接受**行字典**（``dict``），因此既能校验数据库，也能校验内存数据集与测试构造的坏样本；
- ``ERROR`` = 数据不可信/不可用（必须为 0 才算 M1 通过）；``WARNING`` = 质量提示（不阻断）；
- 校验口径全部来自 ``docs/DATA_DICTIONARY.md`` 与 ``docs/DOMAIN_RULES.md`` §2，禁止在此硬编码业务阈值
  （阈值取自 ``ModelParams``）。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from app.core.models import ModelParams
from app.core.rules import RULES, get_rule

# ---------------------------------------------------------------------------
# 报告结构
# ---------------------------------------------------------------------------
ERROR = "ERROR"
WARNING = "WARNING"


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str


@dataclass
class ValidateReport:
    findings: list[Finding] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def add(self, level: str, code: str, message: str) -> None:
        self.findings.append(Finding(level, code, message))

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == ERROR]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == WARNING]

    def error_count(self, code: str) -> int:
        return sum(1 for f in self.findings if f.level == ERROR and f.code == code)

    def warning_count(self, code: str) -> int:
        return sum(1 for f in self.findings if f.level == WARNING and f.code == code)

    def render(self, max_detail: int = 5) -> str:
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("数据质量校验报告（M1）")
        lines.append("=" * 72)
        lines.append("检查表行数：")
        for table, count in sorted(self.checked.items()):
            lines.append(f"  - {table:<22} {count:>7}")
        lines.append("")
        grouped: dict[tuple[str, str], list[Finding]] = defaultdict(list)
        for f in self.findings:
            grouped[(f.level, f.code)].append(f)
        for level in (ERROR, WARNING):
            items = {k: v for k, v in grouped.items() if k[0] == level}
            lines.append(f"---- {level}（{sum(len(v) for v in items.values())} 条）----")
            if not items:
                lines.append("  （无）")
            for (_, code), found in sorted(items.items()):
                lines.append(f"  [{code}] {len(found)} 条")
                for f in found[:max_detail]:
                    lines.append(f"      · {f.message}")
                if len(found) > max_detail:
                    lines.append(f"      … 其余 {len(found) - max_detail} 条省略")
            lines.append("")
        status = "通过（0 error）" if not self.errors() else f"不通过（{len(self.errors())} error）"
        lines.append(f"结论：{status}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _score_for_rank(table: list[tuple[int, int]], rank: int) -> int:
    """与 synthetic.py 同口径的位次→分数线性插值（表按分数降序）。"""
    if not table:
        return 0
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


def _unit_key_of(unit: dict[str, Any]) -> str:
    """由 unit_id 反推 unit_key（去掉年份段）：unit_id = province-year-college-group-major。"""
    parts = str(unit["unit_id"]).split("-")
    if len(parts) < 5:
        return str(unit["unit_id"])
    return "-".join([parts[0], *parts[2:]])


# ---------------------------------------------------------------------------
# 校验主体
# ---------------------------------------------------------------------------
def validate_rows(
    *,
    colleges: Sequence[dict[str, Any]],
    majors: Sequence[dict[str, Any]],
    score_rank_table: Sequence[dict[str, Any]],
    province_year_stats: Sequence[dict[str, Any]],
    admission_units: Sequence[dict[str, Any]],
    admission_plans: Sequence[dict[str, Any]],
    admission_history: Sequence[dict[str, Any]],
    params: ModelParams | None = None,
) -> ValidateReport:
    params = params or ModelParams()
    report = ValidateReport()
    report.checked = {
        "colleges": len(colleges),
        "majors": len(majors),
        "score_rank_table": len(score_rank_table),
        "province_year_stats": len(province_year_stats),
        "admission_units": len(admission_units),
        "admission_plans": len(admission_plans),
        "admission_history": len(admission_history),
    }

    # ---------- 1) 来源纪律：所有表每行必须有 source_url ----------
    for table_name, rows in (
        ("colleges", colleges),
        ("majors", majors),
        ("score_rank_table", score_rank_table),
        ("province_year_stats", province_year_stats),
        ("admission_units", admission_units),
        ("admission_plans", admission_plans),
        ("admission_history", admission_history),
    ):
        missing = sum(1 for r in rows if not (r.get("source_url") or "").strip())
        if missing:
            report.add(ERROR, "SOURCE_URL_MISSING", f"{table_name}: {missing} 行缺 source_url")

    # ---------- 2) 唯一性 ----------
    #
    # ★ M6 勘误（ADR-015）：院校代号只在**省内**唯一，不是全国唯一。
    #   浙江招生用的 0001–9034 是"面向浙江招生的院校顺序号"，其中既有浙江大学也有清华北大；
    #   模拟数据用的是另一套全局号段。真实数据接入后，两者会出现"同代号不同院校"，
    #   这是**正常**的（主键是 ``{省}-{代号}``）。唯一性必须按 ``(province, code)`` 判定。
    college_dup = [
        key
        for key, count in Counter((c.get("province"), c["code"]) for c in colleges).items()
        if count > 1
    ]
    if college_dup:
        report.add(ERROR, "COLLEGE_CODE_DUPLICATE", f"(院校所在地, 院校代号) 重复：{college_dup[:5]}")
    major_code_dup = [c for c, n in Counter(m["code"] for m in majors).items() if n > 1]
    if major_code_dup:
        report.add(ERROR, "MAJOR_CODE_DUPLICATE", f"专业代码重复：{major_code_dup[:5]}")
    unit_id_dup = [k for k, n in Counter(u["unit_id"] for u in admission_units).items() if n > 1]
    if unit_id_dup:
        report.add(ERROR, "UNIT_ID_DUPLICATE", f"unit_id 重复 {len(unit_id_dup)} 个，例：{unit_id_dup[:3]}")
    plan_key_dup = [
        k for k, n in Counter((p["unit_key"], p["year"]) for p in admission_plans).items() if n > 1
    ]
    if plan_key_dup:
        report.add(ERROR, "PLAN_KEY_DUPLICATE", f"(unit_key, year) 重复 {len(plan_key_dup)} 个")
    hist_key_dup = [
        k
        for k, n in Counter(
            (h["unit_key"], h["year"], bool(h["is_collected"])) for h in admission_history
        ).items()
        if n > 1
    ]
    if hist_key_dup:
        report.add(
            ERROR, "HISTORY_KEY_DUPLICATE", f"(unit_key, year, is_collected) 重复 {len(hist_key_dup)} 个"
        )

    # ---------- 3) 一分一段表：单调、累加一致、闭合到总考生数 ----------
    #
    # ★ M6（ADR-015）：跨年归一化的分母是 ``total_candidates``（该年分数段表覆盖的
    #   最低分对应的累计人数）—— 它才是与库中位次同口径的量（浙江合编数据覆盖到二段）。
    #   ``segment1_cumulative``（一段线上线人数）只用于标定曲线，不参与本节的闭合判断。
    stats_index = {
        (s["province"], s["year"], s["track"]): s["total_candidates"]
        for s in province_year_stats
    }
    by_prov_year: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in score_rank_table:
        by_prov_year[(row["province"], row["year"], row["track"])].append(row)
    lookups: dict[tuple[str, int, str], list[tuple[int, int]]] = {}
    for key, rows in sorted(by_prov_year.items()):
        rows.sort(key=lambda r: -r["score"])
        prev_cum = 0
        broken = 0
        for row in rows:
            if row["count_at_score"] < 0:
                report.add(
                    ERROR, "SCORE_COUNT_NEGATIVE", f"{key} score={row['score']} count_at_score<0"
                )
            if row["cumulative_rank"] < prev_cum:
                broken += 1
            if row["cumulative_rank"] != prev_cum + row["count_at_score"]:
                report.add(
                    ERROR,
                    "SCORE_CUMULATIVE_INCONSISTENT",
                    f"{key} score={row['score']}: cumulative != prev + count_at_score",
                )
            prev_cum = row["cumulative_rank"]
        if broken:
            report.add(ERROR, "SCORE_NOT_MONOTONIC", f"{key}: {broken} 处累计位次非单调")
        lookups[key] = [(r["score"], r["cumulative_rank"]) for r in rows]
        total = stats_index.get(key)
        if total is None:
            report.add(ERROR, "SCORE_WITHOUT_STATS", f"{key}: 缺 province_year_stats 元数据")
        elif rows and rows[-1]["cumulative_rank"] != total:
            report.add(
                ERROR,
                "SCORE_TOTAL_MISMATCH",
                f"{key}: 最低分累计位次 {rows[-1]['cumulative_rank']} != 归一化分母 {total}"
                "（位次归一化的分母必须与分数段表口径一致）",
            )

    # ---------- 4) 计划数、选科状态、批次一致性、组内专业数 ----------
    province_batches: dict[str, dict[str, Any]] = {}
    for province, rule in sorted(RULES.items()):
        for batch in rule.batches:
            province_batches[batch.batch_code] = batch
    unit_keys: set[str] = set()
    group_major_count: Counter[tuple[str, str, str]] = Counter()
    for unit in admission_units:
        unit_key = _unit_key_of(unit)
        unit_keys.add(unit_key)
        if unit["plan_count"] is None or unit["plan_count"] <= 0:
            report.add(ERROR, "PLAN_COUNT_NOT_POSITIVE", f"{unit['unit_id']}: plan_count<=0")
        if unit.get("subject_req_status") != "PARSED":
            report.add(
                ERROR,
                "SUBJECT_REQ_NOT_PARSED",
                f"{unit['unit_id']}: subject_req_status={unit.get('subject_req_status')}（必须拒绝入库）",
            )
        try:
            json.loads(unit.get("subject_requirement") or "")
        except (TypeError, ValueError):
            report.add(ERROR, "SUBJECT_REQ_NOT_JSON", f"{unit['unit_id']}: subject_requirement 非法 JSON")
        batch = province_batches.get(unit["batch"])
        if batch is None:
            report.add(ERROR, "UNKNOWN_BATCH", f"{unit['unit_id']}: 批次 {unit['batch']} 无对应 BatchRule")
        else:
            if batch.unit_type.value != unit["unit_type"]:
                report.add(
                    ERROR,
                    "UNIT_TYPE_MISMATCH",
                    f"{unit['unit_id']}: unit_type={unit['unit_type']} 与批次 {batch.batch_code} "
                    f"({batch.unit_type.value}) 不符",
                )
            if unit["province"] != batch.batch_code.split(".")[0]:
                report.add(
                    ERROR, "UNIT_PROVINCE_MISMATCH", f"{unit['unit_id']}: 省份与批次编码不符"
                )
            if batch.unit_type.value == "MAJOR_GROUP":
                group_major_count[(unit["province"], unit["college_id"], unit["group_code"] or "NA")] += 1
    for (province, college_id, group_code), count in sorted(group_major_count.items()):
        rule = get_rule(province)
        batch = rule.main_batch()
        if batch.majors_per_group is not None and count > batch.majors_per_group:
            report.add(
                ERROR,
                "GROUP_MAJORS_EXCEED",
                f"{college_id}/{group_code}: 组内 {count} 个专业 > 上限 {batch.majors_per_group}",
            )

    for plan in admission_plans:
        if plan["plan_count"] is None or plan["plan_count"] <= 0:
            report.add(
                ERROR, "PLAN_COUNT_NOT_POSITIVE", f"{plan['unit_key']}@{plan['year']}: plan_count<=0"
            )
        if plan["unit_key"] not in unit_keys:
            report.add(ERROR, "PLAN_ORPHAN", f"{plan['unit_key']}@{plan['year']}: 无对应投档单位")

    # ---------- 5) 引用完整性 ----------
    college_ids = {c["id"] for c in colleges}
    for unit in admission_units:
        if unit["college_id"] not in college_ids:
            report.add(ERROR, "COLLEGE_REF_MISSING", f"{unit['unit_id']}: 院校不存在")

    # ---------- 6) 历史行：口径、一致性、引用 ----------
    #
    # ★ M6（ADR-015）：一分一段表有两种来源，校验口径必须跟着变
    #   * ``is_synthetic=0``：考试院官方分数段表原文 → 分数↔位次必须严格自洽（±2 分）；
    #   * ``is_synthetic=1``：无官方表，由**当年官方投档记录**（分数↔位次）保序回归标定
    #     并在官方一段线处按官方上线人数闭合 → 它是**估计曲线**，"反查分数 ≠ 该专业实际
    #     最低分"是估计残差，不是数据错误。容忍度放宽到 ``params.modeled_score_gap``，
    #     并且只要存在超差就发 WARNING，绝不让"模型化"这件事悄悄过关。
    modeled_years = {
        (row["province"], row["year"], row["track"])
        for row in score_rank_table
        if row.get("is_synthetic")
    }
    modeled_gap_hits: Counter[int] = Counter()
    total_candidates_ok = 0
    for hist in admission_history:
        key3 = (hist["province"], hist["year"], "综合")
        expected_total = stats_index.get(key3)
        if expected_total is None:
            report.add(ERROR, "HISTORY_WITHOUT_STATS", f"{hist['unit_key']}@{hist['year']}: 缺年度元数据")
        elif hist["total_candidates"] != expected_total:
            report.add(
                ERROR,
                "HISTORY_TOTAL_CANDIDATES_MISMATCH",
                f"{hist['unit_key']}@{hist['year']}: total_candidates={hist['total_candidates']} "
                f"!= province_year_stats {expected_total}（位次归一化分母不得估算）",
            )
        else:
            total_candidates_ok += 1
        if hist["unit_key"] not in unit_keys:
            report.add(ERROR, "HISTORY_ORPHAN", f"{hist['unit_key']}@{hist['year']}: 无对应投档单位")
        quality = hist["data_quality"]
        if bool(hist["is_collected"]) != (quality == "COLLECTED"):
            report.add(
                ERROR,
                "COLLECTED_FLAG_MISMATCH",
                f"{hist['unit_key']}@{hist['year']}: is_collected={hist['is_collected']} 与 "
                f"data_quality={quality} 不一致",
            )
        if quality not in ("OK", "DERIVED", "COLLECTED", "MISSING_RANK", "SUSPECT"):
            report.add(ERROR, "DATA_QUALITY_UNKNOWN", f"未知 data_quality={quality}")
        lookup = lookups.get(key3)
        if hist["min_rank"] is not None and lookup:
            if expected_total and not (1 <= hist["min_rank"] <= expected_total):
                report.add(
                    ERROR, "MIN_RANK_OUT_OF_RANGE", f"{hist['unit_key']}@{hist['year']}: min_rank 越界"
                )
            if hist["min_score"] is not None:
                expect = _score_for_rank(lookup, hist["min_rank"])
                gap = abs(expect - hist["min_score"])
                if key3 in modeled_years:
                    if gap > params.modeled_score_gap:
                        report.add(
                            ERROR,
                            "RANK_SCORE_INCONSISTENT",
                            f"{hist['unit_key']}@{hist['year']}: min_rank={hist['min_rank']} 反查 "
                            f"{expect} 分，实际 {hist['min_score']} 分"
                            f"（超过模型化容忍度 {params.modeled_score_gap}）",
                        )
                    elif gap > params.rank_score_gap:
                        modeled_gap_hits[hist["year"]] += 1
                elif gap > params.rank_score_gap:
                    report.add(
                        ERROR,
                        "RANK_SCORE_INCONSISTENT",
                        f"{hist['unit_key']}@{hist['year']}: min_rank={hist['min_rank']} 反查 "
                        f"{expect} 分，实际 {hist['min_score']} 分",
                    )
    if modeled_gap_hits:
        report.add(
            WARNING,
            "W_RANK_SCORE_MODELED",
            "以下年份的一分一段表为**标定估计**（非官方分数段表），"
            "反查分数与该专业官方最低分存在残差（不影响位次口径）："
            + "，".join(f"{year} {count} 条" for year, count in sorted(modeled_gap_hits.items())),
        )

    # ---------- 7) WARNING：质量提示与注入样本可检出性 ----------
    small_plan = [u for u in admission_units if u["plan_count"] < params.small_plan_warn]
    if small_plan:
        report.add(
            WARNING,
            "W_SMALL_PLAN",
            f"{len(small_plan)} 个单位计划数 < {params.small_plan_warn}（波动大，M2 必须降置信度）",
        )
    derived = sum(1 for h in admission_history if h["data_quality"] == "DERIVED")
    if derived:
        report.add(WARNING, "W_DERIVED", f"{derived} 条历史为 DERIVED（M2 需按 {params.derived_quality_weight} 降权）")
    collected = sum(1 for h in admission_history if h["data_quality"] == "COLLECTED")
    if collected:
        report.add(WARNING, "W_COLLECTED", f"{collected} 条历史来自征集志愿（会高估概率）")
    # "无历史"指**预测可用历史**为空：year < 填报年
    # （当年与未来行是回测地面真值，不得进入预测——模型强制 year < target.year）
    current_year = max((u["year"] for u in admission_units), default=0)
    units_with_prior_history = {
        h["unit_key"] for h in admission_history if current_year and h["year"] < current_year
    }
    no_history = [u for u in admission_units if _unit_key_of(u) not in units_with_prior_history]
    if no_history:
        report.add(
            WARNING,
            "W_NO_HISTORY",
            f"{len(no_history)} 个单位无任何预测可用历史（year < {current_year}）"
            "——含新增专业，M2 必须走 Step 0 类比回退，禁编造概率",
        )
    if current_year:
        ground_truth = [h for h in admission_history if h["year"] == current_year - 1]
        if ground_truth:
            report.add(
                WARNING,
                "W_GROUND_TRUTH",
                f"{len(ground_truth)} 行属于回测地面真值（year={current_year - 1}）："
                "仅用于回测比对，预测时必须按 year < target.year 过滤（防数据泄漏）",
            )

    # 大小年（归一化后 cv 超阈值）与计划突增，均可检出才算"注入了已知规律"
    hist_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hist in admission_history:
        hist_by_key[hist["unit_key"]].append(hist)
    volatile = 0
    for key, rows in sorted(hist_by_key.items()):
        if len(rows) < 2:
            continue
        normalized = [r["min_rank"] / r["total_candidates"] for r in rows if r["total_candidates"]]
        if len(normalized) < 2:
            continue
        mean = statistics.fmean(normalized)
        if mean <= 0:
            continue
        cv = statistics.pstdev(normalized) / mean
        if cv > params.cv_threshold:
            volatile += 1
    report.add(
        WARNING,
        "W_VOLATILE_UNITS",
        f"{volatile} 个单位历史位次 cv > {params.cv_threshold}（大小年样本，M2 应收缩概率并打风险）",
    )

    plans_by_key: dict[str, dict[int, int]] = defaultdict(dict)
    for plan in admission_plans:
        plans_by_key[plan["unit_key"]][plan["year"]] = plan["plan_count"]
    spikes = 0
    for key, years in sorted(plans_by_key.items()):
        if 2024 in years and 2025 in years and years[2024]:
            delta = (years[2025] - years[2024]) / years[2024]
            if abs(delta) >= params.plan_delta_clip * 0.8:  # ≥40% 视为显著突增
                spikes += 1
    report.add(WARNING, "W_PLAN_SPIKE", f"{spikes} 个单位 2025 计划相对 2024 变动 ≥40%")

    # 规则核实红线：全省批次均未达 PRIMARY 的省份，推荐结果不得用于真实填报
    redline = sorted(
        province
        for province, rule in RULES.items()
        if all(b.verified_status.value in ("SECONDARY", "UNVERIFIED") for b in rule.batches)
    )
    partial = sorted(
        province
        for province, rule in RULES.items()
        if province not in redline
        and any(b.verified_status.value != "PRIMARY" for b in rule.batches)
    )
    if redline:
        report.add(
            WARNING,
            "W_RULE_REDLINE",
            f"以下省份全部批次均未达 PRIMARY，推荐结果**不得用于真实填报**，"
            f"UI 必须显示「规则待核实」横幅：{', '.join(redline)}",
        )
    if partial:
        report.add(
            WARNING,
            "W_RULE_NOT_PRIMARY",
            f"以下省份存在未达 PRIMARY 的批次（UI 需按批次提示核实状态）：{', '.join(partial)}",
        )

    if not admission_units:
        report.add(ERROR, "EMPTY_DATASET", "admission_units 为空：请先运行 scripts/seed.py")
    return report


# ---------------------------------------------------------------------------
# 数据库入口
# ---------------------------------------------------------------------------
def load_rows_from_db() -> dict[str, list[dict[str, Any]]]:
    """从数据库读出全部行（dict 形式）。"""
    from sqlalchemy import select

    from app.db import models as m
    from app.db.session import SessionLocal

    mapping = {
        "colleges": m.College,
        "majors": m.Major,
        "score_rank_table": m.ScoreRankTable,
        "province_year_stats": m.ProvinceYearStats,
        "admission_units": m.AdmissionUnitRow,
        "admission_plans": m.AdmissionPlan,
        "admission_history": m.AdmissionHistory,
    }
    out: dict[str, list[dict[str, Any]]] = {}
    with SessionLocal() as session:
        for name, model in mapping.items():
            columns = [c.name for c in model.__table__.columns]
            out[name] = [
                {col: getattr(obj, col) for col in columns}
                for obj in session.execute(select(model)).scalars()
            ]
    return out


def validate_database(params: ModelParams | None = None) -> ValidateReport:
    return validate_rows(**load_rows_from_db(), params=params)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="数据质量校验（M1）")
    parser.add_argument("--report", action="store_true", help="打印完整报告")
    parser.add_argument("--max-detail", type=int, default=5, help="每类问题最多打印条数")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = validate_database()
    print(report.render(max_detail=args.max_detail))
    return 1 if report.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
