"""风险扫描测试（AGENTS.md §6.8）：14 个风险码全覆盖 + 顺序志愿分支。"""

from __future__ import annotations

from app.core.models import (
    ModelParams,
    PhysicalExam,
    PlanItem,
    Preferences,
    RiskLevel,
    Tier,
    VolunteerPlan,
)
from app.core.risk import (
    ALL_RISK_CODES,
    COLLECTED_ONLY,
    GRADIENT_INVERSION,
    GROUP_UNACCEPTABLE,
    INSUFFICIENT_COUNT,
    NO_HISTORY,
    NO_OBEDIENCE,
    NO_SAFETY_NET,
    PHYSICAL_LIMIT,
    PLAN_TOO_SMALL,
    SAFETY_NOT_SAFE,
    SINGLE_YEAR_DATA,
    SUSPECT_DATA,
    TUITION_HIGH,
    VOLATILE_HISTORY,
    risk_summary,
    scan_risks,
)
from app.core.rules import get_rule

from factories import make_history, make_student, make_unit

PARAMS = ModelParams()
ZJ = get_rule("zhejiang")
SH = get_rule("shanghai")


def _item(position: int, unit, tier: Tier, probability: float = 0.6, obey: bool | None = None) -> PlanItem:
    return PlanItem(
        position=position,
        unit=unit,
        tier=tier,
        probability=probability,
        utility=probability,
        obey_adjustment=obey,
    )


def _plan(rule, batch, items: list[PlanItem]) -> VolunteerPlan:
    return VolunteerPlan(
        id="p1",
        student_id="s1",
        province=rule.province,
        rule=rule.rule_info(batch),
        items=items,
    )


def _safe_units(count: int, *, rank: int = 20000, tier: Tier = Tier.DIAN, **kwargs):
    """构造历史位次远优于考生位次的"真保底"单位。"""
    items = []
    for index in range(count):
        unit = make_unit(college=f"{3000 + index}", major=f"1002{index:02d}", **kwargs)
        key = f"zhejiang-{3000 + index}-NA-1002{index:02d}"
        items.append((unit, key))
    return items


def test_all_fourteen_codes_declared() -> None:
    assert len(ALL_RISK_CODES) == 14
    assert len(set(ALL_RISK_CODES)) == 14


def test_clean_parallel_plan_has_no_high_risks() -> None:
    batch = ZJ.main_batch()
    student = make_student(20000)
    units = _safe_units(80, rank=20000)
    items = [
        _item(index + 1, unit, Tier.DIAN if index < 10 else Tier.BAO)
        for index, (unit, _) in enumerate(units)
    ]
    # 真保底：该单位近三年最难年份的切线也要比考生位次靠后 ≥ safety_margin
    # （默认 safety_margin=0.60，见 DECISIONS ADR-014：考生 20000 × 1.60 = 32000 →
    #  历史位次取 36000 档，留出 80% 余量；min_sigma_rel 等参数改动不影响本用例）
    histories = {key: make_history(key, {2025: 36000, 2024: 37000, 2023: 36500}) for _, key in units}
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=student,
        histories=histories,
        params=PARAMS,
        batch=batch,
        current_total_candidates=400_000,
    )
    assert [risk.code for risk in risks if risk.level is RiskLevel.HIGH] == []


def test_no_safety_net_when_dian_missing() -> None:
    batch = ZJ.main_batch()
    items = [_item(1, make_unit(), Tier.CHONG)]
    risks = scan_risks(
        _plan(ZJ, batch, items), student=make_student(), histories={}, params=PARAMS, batch=batch
    )
    assert NO_SAFETY_NET in {risk.code for risk in risks}


def test_safety_not_safe_when_history_not_better() -> None:
    batch = ZJ.main_batch()
    student = make_student(20000)
    units = _safe_units(3)
    items = [_item(index + 1, unit, Tier.DIAN) for index, (unit, _) in enumerate(units)]
    # 历史位次 19000 未优于考生位次的 85%（=17000）
    histories = {key: make_history(key, {2025: 19000, 2024: 19500, 2023: 19200}) for _, key in units}
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=student,
        histories=histories,
        params=PARAMS,
        batch=batch,
        current_total_candidates=400_000,
    )
    assert SAFETY_NOT_SAFE in {risk.code for risk in risks}


def test_insufficient_count_and_plan_too_small() -> None:
    batch = ZJ.main_batch()
    items = [_item(1, make_unit(plan_count=3), Tier.WEN)]
    risks = scan_risks(
        _plan(ZJ, batch, items), student=make_student(), histories={}, params=PARAMS, batch=batch
    )
    codes = {risk.code for risk in risks}
    assert INSUFFICIENT_COUNT in codes
    assert PLAN_TOO_SMALL in codes


def test_volatile_no_history_and_single_year() -> None:
    batch = ZJ.main_batch()
    volatile_unit = make_unit(college="3001")
    single_unit = make_unit(college="3002", major="100202")
    none_unit = make_unit(college="3003", major="100203")
    items = [
        _item(1, volatile_unit, Tier.BAO),
        _item(2, single_unit, Tier.WEN),
        _item(3, none_unit, Tier.DIAN),
    ]
    histories = {
        "zhejiang-3001-NA-100111": make_history("zhejiang-3001-NA-100111", {2025: 7000, 2024: 12000, 2023: 7500}),
        "zhejiang-3002-NA-100202": make_history("zhejiang-3002-NA-100202", {2025: 9000}),
    }
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=make_student(15000),
        histories=histories,
        params=PARAMS,
        batch=batch,
        current_total_candidates=400_000,
    )
    codes = {risk.code for risk in risks}
    assert {VOLATILE_HISTORY, SINGLE_YEAR_DATA, NO_HISTORY} <= codes


def test_suspect_and_collected_only() -> None:
    batch = ZJ.main_batch()
    suspect_unit = make_unit(college="3101")
    collected_unit = make_unit(college="3102", major="100302")
    items = [_item(1, suspect_unit, Tier.BAO), _item(2, collected_unit, Tier.WEN)]
    histories = {
        "zhejiang-3101-NA-100111": make_history("zhejiang-3101-NA-100111", {2025: 9000}, data_quality="SUSPECT"),
        "zhejiang-3102-NA-100302": make_history(
            "zhejiang-3102-NA-100302", {2025: 9000, 2024: 9200}, data_quality="COLLECTED", is_collected=True
        ),
    }
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=make_student(9000),
        histories=histories,
        params=PARAMS,
        batch=batch,
        current_total_candidates=400_000,
    )
    codes = {risk.code for risk in risks}
    assert SUSPECT_DATA in codes
    assert COLLECTED_ONLY in codes


def test_gradient_inversion_detected() -> None:
    batch = ZJ.main_batch()
    weak = make_unit(college="3201", major_name="哲学")
    strong = make_unit(college="3202", major="100402", major_name="临床医学")
    items = [
        _item(1, weak, Tier.BAO, probability=0.80),
        _item(2, strong, Tier.BAO, probability=0.90),
    ]
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=make_student(15000),
        histories={},
        params=PARAMS,
        batch=batch,
        college_level_tags={"zhejiang-3201": [], "zhejiang-3202": ["985", "211", "双一流"]},
    )
    assert GRADIENT_INVERSION in {risk.code for risk in risks}


def test_no_obedience_and_group_unacceptable() -> None:
    batch = SH.main_batch()  # 院校专业组，有调剂
    unit = make_unit(
        province="shanghai",
        batch=batch.batch_code,
        group="G1",
        unit_type=batch.unit_type,
        college="4001",
        major="100501",
    )
    student = make_student(
        province="shanghai",
        preferences=Preferences(excluded_majors=["护理学"]),
    )
    items = [_item(1, unit, Tier.WEN, obey=None)]
    risks = scan_risks(
        _plan(SH, batch, items),
        student=student,
        histories={},
        params=PARAMS,
        batch=batch,
        group_majors={("shanghai-4001", "G1"): ["护理学", "临床医学"]},
    )
    codes = {risk.code for risk in risks}
    assert NO_OBEDIENCE in codes
    assert GROUP_UNACCEPTABLE in codes


def test_physical_limit_and_tuition_high() -> None:
    batch = ZJ.main_batch()
    unit = make_unit(college="4101", tuition=45000, physical_requirements=["色盲不宜"])
    student = make_student(
        15000,
        physical_exam=PhysicalExam(color_blindness=True),
        preferences=Preferences(budget_comfortable=10000, budget_max=60000),
    )
    risks = scan_risks(
        _plan(ZJ, batch, [_item(1, unit, Tier.WEN)]),
        student=student,
        histories={},
        params=PARAMS,
        batch=batch,
    )
    codes = {risk.code for risk in risks}
    assert PHYSICAL_LIMIT in codes
    assert TUITION_HIGH in codes


def test_sequential_batch_skips_gradient_codes() -> None:
    batch = ZJ.get_batch("zhejiang.advance.college")  # 顺序志愿，上限 5
    unit = make_unit(
        batch=batch.batch_code,
        college="5001",
        group="G1",
        unit_type=batch.unit_type,
    )
    items = [_item(index + 1, unit, Tier.CHONG) for index in range(3)]
    risks = scan_risks(
        _plan(ZJ, batch, items),
        student=make_student(15000),
        histories={},
        params=PARAMS,
        batch=batch,
    )
    codes = {risk.code for risk in risks}
    assert not codes & {NO_SAFETY_NET, SAFETY_NOT_SAFE, GRADIENT_INVERSION, INSUFFICIENT_COUNT}


def test_risks_sorted_high_first_and_summarised() -> None:
    batch = ZJ.main_batch()
    items = [_item(1, make_unit(plan_count=3, physical_requirements=["色盲不宜"]), Tier.CHONG)]
    student = make_student(15000, physical_exam=PhysicalExam(color_blindness=True))
    risks = scan_risks(
        _plan(ZJ, batch, items), student=student, histories={}, params=PARAMS, batch=batch
    )
    levels = [risk.level for risk in risks]
    assert levels == sorted(levels, key=lambda level: 0 if level is RiskLevel.HIGH else (1 if level is RiskLevel.MEDIUM else 2))
    assert all(risk.suggestion for risk in risks)
    assert sum(risk_summary(risks).values()) == len(risks)
