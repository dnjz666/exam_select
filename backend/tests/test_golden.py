"""黄金用例执行器（M2 验收：≥20 条**人工期望**用例全过，AGENTS.md §7 / DOMAIN_RULES §7）。

用例按 kind 分组存放于 ``tests/golden/*.json``：
- ``probability``：概率模型（期望值由 §6.2 八步公式人工推导，``derivation`` 记录中间量）；
- ``filter``：硬约束过滤（期望：通过 or 具体剔除码）；
- ``plan_rule``：志愿表批次级规则校验（期望：违规码集合）。

⚠️ 已知文档勘误（见 ADR-009 / DOMAIN_RULES §7 注记）：
DOMAIN_RULES §7 的 G-001 示例（考生 10000 vs 单位 9000/9500/9200 却期望"稳档"）
与 §7.2 的"历史位次整体变小 → 概率不下降"均与 §2.1 位次口径及 §6.2 公式矛盾。
本执行器按**公式与统一口径**断言，并用 G-018 锁定方向，防止后人照错误示例"改回去"。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.filters import check_unit
from app.core.models import (
    AdmissionRecord,
    AdmissionUnit,
    DataQuality,
    FilterCriteria,
    ModelParams,
    PhysicalExam,
    PlanItem,
    Preferences,
    StudentProfile,
    SubjectRequirement,
    Tier,
    UnitType,
    VolunteerPlan,
)
from app.core.probability import AnalogUnit, estimate_probability
from app.core.rules import batch_by_code, get_rule

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
_CASE_YEAR = 2025
_PROVINCE = "zhejiang"
_COLLEGE = "1001"
_MAJOR = "100111"
_GROUP = None
_UNIT_KEY = f"{_PROVINCE}-{_COLLEGE}-{_GROUP or 'NA'}-{_MAJOR}"
_UNIT_ID = f"{_PROVINCE}-{_CASE_YEAR}-{_COLLEGE}-{_GROUP or 'NA'}-{_MAJOR}"
_BATCH = "zhejiang.public.seg1"


def _load(kind: str) -> list[dict]:
    cases: list[dict] = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("kind") == kind:
            cases.extend(payload["cases"])
    return cases


PROBABILITY_CASES = _load("probability")
FILTER_CASES = _load("filter")
PLAN_RULE_CASES = _load("plan_rule")
ALL_CASES = PROBABILITY_CASES + FILTER_CASES + PLAN_RULE_CASES


def _student(data: dict, *, province: str = _PROVINCE, year: int = _CASE_YEAR) -> StudentProfile:
    physical = data.get("physical") or {}
    return StudentProfile(
        id="golden-student",
        province=province,
        year=year,
        subjects=data.get("subjects", ["物理", "化学", "生物"]),
        total_score=data.get("total_score", 640),
        rank=data.get("rank"),
        physical_exam=PhysicalExam(
            color_blindness=bool(physical.get("color_blindness", False)),
            color_weakness=bool(physical.get("color_weakness", False)),
            height_cm=physical.get("height_cm"),
            other_restrictions=list(physical.get("other_restrictions", [])),
        ),
        gender=data.get("gender"),
        foreign_language=data.get("foreign_language", "英语"),
        single_subject_scores=dict(data.get("single_subject_scores", {}) or {}),
        preferences=Preferences(**data.get("preferences", {})),
    )


def _target_unit(case: dict) -> AdmissionUnit:
    return AdmissionUnit(
        unit_id=_UNIT_ID,
        unit_type=UnitType.MAJOR_COLLEGE,
        province=_PROVINCE,
        year=_CASE_YEAR,
        batch=_BATCH,
        college_id=f"{_PROVINCE}-{_COLLEGE}",
        group_code=_GROUP,
        major_id=f"工学-{_MAJOR}",
        major_name="计算机科学与技术",
        subject_requirement=SubjectRequirement(),
        plan_count=int(case["plan_count_current"]),
        tuition=6000,
    )


def _records(case: dict) -> list[AdmissionRecord]:
    total = case.get("current_total_candidates")
    records: list[AdmissionRecord] = []
    for row in case.get("history", []):
        records.append(
            AdmissionRecord(
                unit_key=_UNIT_KEY,
                province=_PROVINCE,
                year=int(row["year"]),
                batch=_BATCH,
                unit_type=UnitType.MAJOR_COLLEGE,
                college_id=f"{_PROVINCE}-{_COLLEGE}",
                major_id=f"工学-{_MAJOR}",
                min_score=row.get("min_score"),
                min_rank=row.get("min_rank"),
                plan_count=row.get("plan_count"),
                is_collected=bool(row.get("is_collected", False)),
                data_quality=DataQuality(row.get("data_quality", "OK")),
                total_candidates=total,
                source_url="synthetic://golden",
            )
        )
    return records


def _analogs(case: dict) -> list[AnalogUnit]:
    total = case.get("current_total_candidates")
    analogs: list[AnalogUnit] = []
    for row in case.get("analog_pool", []):
        parts = str(row["unit_key"]).split("-")
        province, college, group, major = parts[0], parts[1], parts[2], parts[3]
        unit = AdmissionUnit(
            unit_id=f"{province}-{_CASE_YEAR}-{college}-{group}-{major}",
            unit_type=UnitType.MAJOR_COLLEGE,
            province=province,
            year=_CASE_YEAR,
            batch=f"{province}.public.seg1" if province == "zhejiang" else _BATCH,
            college_id=f"{province}-{college}",
            group_code=None if group == "NA" else group,
            major_id=f"工学-{major}",
            major_name="计算机科学与技术",
            plan_count=20,
            tuition=6000,
        )
        analogs.append(
            AnalogUnit(
                unit=unit,
                records=[
                    AdmissionRecord(
                        unit_key=row["unit_key"],
                        province=province,
                        year=_CASE_YEAR - 1,
                        batch=unit.batch,
                        unit_type=UnitType.MAJOR_COLLEGE,
                        college_id=unit.college_id,
                        major_id=unit.major_id,
                        min_rank=int(row["min_rank"]),
                        plan_count=20,
                        data_quality=DataQuality.OK,
                        total_candidates=total,
                        source_url="synthetic://golden",
                    )
                ],
                level_tags=tuple(row.get("level_tags", [])),
                discipline=row.get("discipline"),
                college_province=row.get("college_province"),
            )
        )
    return analogs


# ---------------------------------------------------------------------------
# 用例数量与覆盖（M2 完成定义：20 条黄金用例）
# ---------------------------------------------------------------------------
def test_golden_case_inventory() -> None:
    assert len(ALL_CASES) >= 20, f"黄金用例不足 20 条：{len(ALL_CASES)}"
    assert len({case["case_id"] for case in ALL_CASES}) == len(ALL_CASES), "case_id 必须唯一"
    assert len(PROBABILITY_CASES) >= 12
    assert len(FILTER_CASES) >= 6
    assert len(PLAN_RULE_CASES) >= 3
    # 每条用例都必须有 description 与（概率用例的）derivation，便于人工复核
    for case in ALL_CASES:
        assert case.get("description"), case["case_id"]
    for case in PROBABILITY_CASES:
        assert case.get("derivation"), case["case_id"]


# ---------------------------------------------------------------------------
# 概率用例
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "case", PROBABILITY_CASES, ids=[case["case_id"] for case in PROBABILITY_CASES]
)
def test_golden_probability(case: dict) -> None:
    rule = get_rule(_PROVINCE)
    result = estimate_probability(
        _student(case["student"]),
        _target_unit(case),
        _records(case),
        rule,
        ModelParams(),
        current_total_candidates=case.get("current_total_candidates"),
        analog_pool=_analogs(case),
    )
    expected = case["expected"]

    assert result.tier.value == expected["tier"], (
        f"{case['case_id']} 分层不符：得到 {result.tier.value}（P={result.probability}），"
        f"期望 {expected['tier']}；推导：{case.get('derivation')}"
    )
    assert result.confidence.value == expected["confidence"], case["case_id"]

    if expected.get("prob_is_none"):
        assert result.probability is None, case["case_id"]
    else:
        assert result.probability is not None, case["case_id"]
        assert expected["prob_min"] <= result.probability <= expected["prob_max"], (
            f"{case['case_id']} 概率 {result.probability:.4f} 不在 "
            f"[{expected['prob_min']}, {expected['prob_max']}]；推导：{case.get('derivation')}"
        )
    for warning in expected.get("warnings_include", []):
        assert warning in result.warnings, f"{case['case_id']} 缺少警告 {warning}：{result.warnings}"


# ---------------------------------------------------------------------------
# 过滤用例
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", FILTER_CASES, ids=[case["case_id"] for case in FILTER_CASES])
def test_golden_filter(case: dict) -> None:
    unit_data = case.get("unit", {})
    unit = _target_unit({"plan_count_current": 20})
    unit = unit.model_copy(
        update={
            "subject_requirement": SubjectRequirement(**unit_data.get("subject_requirement", {})),
            "tuition": int(unit_data.get("tuition", 6000)),
            "gender_limit": unit_data.get("gender_limit"),
            "physical_requirements": list(unit_data.get("physical_requirements", [])),
            "foreign_language_requirement": unit_data.get("foreign_language_requirement"),
            "single_subject_min": dict(unit_data.get("single_subject_min", {})),
            "fresh_graduate_only": bool(unit_data.get("fresh_graduate_only", False)),
            "political_requirement": unit_data.get("political_requirement"),
            "is_withdrawn": bool(unit_data.get("is_withdrawn", False)),
        }
    )
    criteria = FilterCriteria(**case.get("criteria", {}))
    reason = check_unit(unit, _student(case["student"]), criteria=criteria)
    expected = case["expected"]
    if expected["passed"]:
        assert reason is None, f"{case['case_id']} 期望通过，实际被剔除：{reason}"
    else:
        assert reason is not None, case["case_id"]
        assert reason.rule_code == expected["rule_code"], (
            f"{case['case_id']} 剔除码 {reason.rule_code} != {expected['rule_code']}"
        )


# ---------------------------------------------------------------------------
# 志愿表规则用例
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "case", PLAN_RULE_CASES, ids=[case["case_id"] for case in PLAN_RULE_CASES]
)
def test_golden_plan_rule(case: dict) -> None:
    rule, batch = batch_by_code(case["batch_code"])
    items: list[PlanItem] = []
    for index, raw in enumerate(case["items"], start=1):
        group = raw.get("group")
        unit = AdmissionUnit(
            unit_id=f"{case['province']}-{_CASE_YEAR}-{raw['college']}-{group or 'NA'}-{raw['major']}",
            unit_type=UnitType(raw.get("unit_type", batch.unit_type.value)),
            province=case["province"],
            year=_CASE_YEAR,
            batch=case["batch_code"],
            college_id=f"{case['province']}-{raw['college']}",
            group_code=group,
            major_id=f"工学-{raw['major']}",
            major_name="计算机科学与技术",
            plan_count=20,
            tuition=6000,
        )
        items.append(
            PlanItem(
                position=index,
                unit=unit,
                tier=Tier.WEN,
                probability=0.6,
                obey_adjustment=raw.get("obey_adjustment"),
            )
        )
    plan = VolunteerPlan(
        id=f"golden-{case['case_id']}",
        student_id="golden-student",
        province=case["province"],
        rule=rule.rule_info(batch),
        items=items,
    )
    codes = {violation.code for violation in rule.validate_plan(plan, batch)}
    for expected_code in case["expected"]["violation_codes_include"]:
        assert expected_code in codes, f"{case['case_id']} 缺少违规码 {expected_code}：{sorted(codes)}"
    for forbidden in case["expected"].get("violation_codes_exclude", []):
        assert forbidden not in codes, f"{case['case_id']} 不应出现 {forbidden}"
