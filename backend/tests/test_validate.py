"""数据质量校验器测试（M1）：干净数据 0 error，坏数据必须被检出。

设计：模块级生成一次数据集，测试内**复制**再局部破坏，
既快又能保证"每条 ERROR 码都有对应的检出测试"。
"""

from __future__ import annotations

import pytest

from app.etl.synthetic import generate
from app.etl.validate import ERROR, validate_rows

_TABLES = (
    "colleges",
    "majors",
    "score_rank_table",
    "province_year_stats",
    "admission_units",
    "admission_plans",
    "admission_history",
)


@pytest.fixture(scope="module")
def dataset():
    return generate()


@pytest.fixture()
def rows(dataset) -> dict[str, list[dict]]:
    """每次测试拿到一份可安全破坏的副本。"""
    return {name: [dict(r) for r in getattr(dataset, name)] for name in _TABLES}


def _codes(report, level: str = ERROR) -> set[str]:
    return {f.code for f in report.findings if f.level == level}


def test_generated_dataset_has_zero_errors(rows) -> None:
    report = validate_rows(**rows)
    assert report.errors() == [], report.render()
    # 注入的规律必须作为 WARNING 出现（可检出性）
    warnings = _codes(report, "WARNING")
    assert {
        "W_SMALL_PLAN",
        "W_NO_HISTORY",
        "W_VOLATILE_UNITS",
        "W_PLAN_SPIKE",
        "W_RULE_REDLINE",
        "W_RULE_NOT_PRIMARY",
    } <= warnings
    # 红线省份必须恰好是天津/海南（全省批次均未达 PRIMARY）
    redline = next(f for f in report.findings if f.code == "W_RULE_REDLINE")
    assert "tianjin" in redline.message and "hainan" in redline.message


def test_detects_missing_source_url(rows) -> None:
    rows["admission_units"][0]["source_url"] = ""
    assert "SOURCE_URL_MISSING" in _codes(validate_rows(**rows))


def test_detects_non_positive_plan_count(rows) -> None:
    rows["admission_units"][0]["plan_count"] = 0
    rows["admission_plans"][0]["plan_count"] = -3
    assert _codes(validate_rows(**rows)) >= {"PLAN_COUNT_NOT_POSITIVE"}


def test_detects_non_monotonic_score_table(rows) -> None:
    rows["score_rank_table"].sort(key=lambda r: (r["province"], r["year"], -r["score"]))
    target = rows["score_rank_table"][10]
    target["cumulative_rank"] = 1  # 制造累计位次倒退
    assert "SCORE_NOT_MONOTONIC" in _codes(validate_rows(**rows))


def test_detects_score_total_mismatch(rows) -> None:
    rows["score_rank_table"].sort(key=lambda r: (r["province"], r["year"], -r["score"]))
    last_of_group = rows["score_rank_table"][0]
    last_of_group["cumulative_rank"] = 12345  # 与 province_year_stats 不闭合
    report = validate_rows(**rows)
    assert _codes(report) & {"SCORE_TOTAL_MISMATCH", "SCORE_CUMULATIVE_INCONSISTENT"}


def test_detects_rank_score_inconsistency(rows) -> None:
    row = rows["admission_history"][0]
    row["min_score"] = (row["min_score"] or 500) - 200  # 位次与分数明显矛盾
    assert "RANK_SCORE_INCONSISTENT" in _codes(validate_rows(**rows))


def test_detects_collected_flag_mismatch(rows) -> None:
    row = rows["admission_history"][0]
    row["is_collected"] = True
    if row["data_quality"] == "COLLECTED":
        row["data_quality"] = "OK"
    assert "COLLECTED_FLAG_MISMATCH" in _codes(validate_rows(**rows))


def test_detects_duplicate_unit_id_and_keys(rows) -> None:
    rows["admission_units"].append(dict(rows["admission_units"][0]))
    rows["admission_plans"].append(dict(rows["admission_plans"][0]))
    rows["admission_history"].append(dict(rows["admission_history"][0]))
    assert _codes(validate_rows(**rows)) >= {
        "UNIT_ID_DUPLICATE",
        "PLAN_KEY_DUPLICATE",
        "HISTORY_KEY_DUPLICATE",
    }


def test_detects_orphans_and_bad_subject_req(rows) -> None:
    rows["admission_plans"][0]["unit_key"] = "zhejiang-9999-NA-999999"
    rows["admission_history"][0]["unit_key"] = "zhejiang-9999-NA-999999"
    rows["admission_units"][0]["subject_req_status"] = "PARSE_FAILED"
    rows["admission_units"][1]["subject_requirement"] = "{not json"
    assert _codes(validate_rows(**rows)) >= {
        "PLAN_ORPHAN",
        "HISTORY_ORPHAN",
        "SUBJECT_REQ_NOT_PARSED",
        "SUBJECT_REQ_NOT_JSON",
    }


def test_detects_unit_type_mismatch_against_batch_rule(rows) -> None:
    rows["admission_units"][0]["unit_type"] = "MAJOR_COLLEGE"
    rows["admission_units"][0]["batch"] = "shanghai.undergrad.regular"  # 上海要求 MAJOR_GROUP
    assert "UNIT_TYPE_MISMATCH" in _codes(validate_rows(**rows))


def test_detects_group_majors_exceeding_limit(rows) -> None:
    """把上海某组内的专业数灌到超过 BatchRule.majors_per_group。"""
    shanghai_units = [u for u in rows["admission_units"] if u["province"] == "shanghai"]
    base = shanghai_units[0]
    for extra in range(10):
        clone = dict(base)
        clone["unit_id"] = f"{base['unit_id']}-X{extra}"
        rows["admission_units"].append(clone)
    assert "GROUP_MAJORS_EXCEED" in _codes(validate_rows(**rows))


def test_detects_empty_dataset(rows) -> None:
    rows["admission_units"] = []
    assert "EMPTY_DATASET" in _codes(validate_rows(**rows))
