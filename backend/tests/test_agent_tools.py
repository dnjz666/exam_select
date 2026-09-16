"""工具层单测（AGENTS.md §9.1）。

两条硬约束必须被测试守住：
1. **每个数字都带来源**：返回的 ``evidence`` 非空，且数值字段能在 ``data`` 里找到对应来源；
2. **绝不写库**：``generate_plan`` 是只读预览——跑完之后库里不能多出志愿表。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.agent.tools import TOOL_REGISTRY, TOOL_SCHEMAS, ToolContext, call_tool
from app.core.rules import PROVINCES
from app.db import models as db
from app.db.session import SessionLocal
from app.etl.synthetic import CURRENT_YEAR

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        units = session.execute(select(func.count()).select_from(db.AdmissionUnitRow)).scalar_one()
    if units == 0:
        pytest.fail(
            "数据库为空，agent 工具测试无法运行。请先执行："
            "backend\\.venv\\Scripts\\python.exe scripts\\seed.py --reset"
        )


@pytest.fixture()
def session():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def student_id(session) -> str:
    from app.services import student_service

    row = student_service.create(
        session,
        {
            "province": "zhejiang",
            "year": CURRENT_YEAR,
            "subjects": ["物理", "化学", "生物"],
            "total_score": 640,
        },
    )
    session.commit()
    return row.id


@pytest.fixture()
def ctx(session, student_id) -> ToolContext:
    return ToolContext(session=session, student_id=student_id)


# ---------------------------------------------------------------------------
# 注册表与 schema
# ---------------------------------------------------------------------------
def test_tool_schemas_are_strict() -> None:
    """所有工具的参数 schema 必须显式声明 required 且禁止额外字段。"""
    assert len(TOOL_SCHEMAS) >= 11, "AGENTS.md §9.1 至少 11 个工具"
    for schema in TOOL_SCHEMAS:
        function = schema["function"]
        assert schema["type"] == "function"
        assert function["description"], function["name"]
        parameters = function["parameters"]
        assert parameters["type"] == "object"
        assert parameters["additionalProperties"] is False, function["name"]
        assert "required" in parameters, function["name"]
        for name in parameters["required"]:
            assert name in parameters["properties"], f"{function['name']}.{name}"


def test_all_agents_tools_are_read_only_by_name() -> None:
    """工具名里不得出现写操作语义（真正的保证由 test_tool_generate_plan_does_not_write 给出）。"""
    for name in TOOL_REGISTRY:
        assert not name.startswith(("create_", "save_", "update_", "delete_")), name


# ---------------------------------------------------------------------------
# 数字必须带来源
# ---------------------------------------------------------------------------
def test_province_rule_carries_official_source(ctx: ToolContext) -> None:
    result = call_tool(ctx, "get_province_rule", {"province": "zhejiang"})
    assert result.ok
    assert result.data["main_batch"]["max_volunteers"] == 80
    assert result.evidence, "规则数字必须带来源"
    assert all(entry["source_url"] for entry in result.evidence)
    assert result.data["main_batch"]["source_quote"], "必须带官方原文摘录"


def test_rank_lookup_is_sourced(ctx: ToolContext) -> None:
    result = call_tool(
        ctx, "get_rank_by_score", {"province": "zhejiang", "year": CURRENT_YEAR, "score": 640}
    )
    assert result.ok
    assert result.data["rank"] > 0
    assert result.data["total_candidates"] > 0
    assert result.evidence[0]["what"] == "score_rank_table"
    assert result.evidence[0]["source_url"]


def test_rank_lookup_reports_missing_table_instead_of_guessing(ctx: ToolContext) -> None:
    """一分一段表缺失时**必须**报错，不能用估算值糊弄（§8.1 红线）。"""
    result = call_tool(ctx, "get_rank_by_score", {"province": "jiangsu", "year": CURRENT_YEAR, "score": 640})
    assert result.ok is False
    assert result.error["code"] in {"RANK_UNAVAILABLE", "NOT_FOUND"}


def test_search_units_returns_sourced_rows(ctx: ToolContext) -> None:
    result = call_tool(ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "limit": 5})
    assert result.ok
    assert result.data["count"] == 5
    for unit in result.data["units"]:
        for field in ("unit_id", "college_name", "major_name", "plan_count", "tuition", "source_url"):
            assert field in unit, field
        assert unit["source_url"], "计划数必须能追到来源"


def test_search_units_filters_by_keyword(ctx: ToolContext) -> None:
    """关键词过滤必须真的生效：用池内某院校名去搜，结果都应是该校。"""
    first = call_tool(ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "limit": 1})
    name = first.data["units"][0]["college_name"]
    result = call_tool(
        ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "keyword": name}
    )
    assert result.ok and result.data["count"] >= 1
    assert all(unit["college_name"] == name for unit in result.data["units"])


def test_search_units_for_unknown_keyword_says_so(ctx: ToolContext) -> None:
    """查不到就是数据缺失——返回空 + 明确警告，**不返回一个编造的结果**。"""
    result = call_tool(
        ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "keyword": "华夏科技大学"}
    )
    assert result.ok
    assert result.data["count"] == 0
    assert result.warnings, "查不到必须有警告，否则模型会以为'没有就是没有数据'之外还可以自由发挥"


def test_history_tool_reports_missing_history(ctx: ToolContext) -> None:
    result = call_tool(ctx, "get_unit_history", {"unit_id": "zhejiang-2026-NA-000000"})
    assert result.ok is False
    assert result.error["code"] == "NO_HISTORY"


def test_probability_tool_returns_interval_and_evidence(ctx: ToolContext) -> None:
    search = call_tool(ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "limit": 1})
    unit_id = search.data["units"][0]["unit_id"]
    result = call_tool(ctx, "estimate_probability", {"unit_id": unit_id})
    assert result.ok
    assert result.data["probability"] is not None
    assert len(result.data["probability_interval"]) == 2, "UI 只显示区间（§8）"
    assert result.evidence


def test_recommend_units_is_sourced(ctx: ToolContext) -> None:
    result = call_tool(ctx, "recommend_units", {"limit": 5})
    assert result.ok
    items = result.data["items"]
    assert items, "完整档案应能推荐出结果"
    assert all(item["evidence"] for item in items), "契约铁律 1：每项 evidence 非空"
    assert result.evidence


def test_unknown_college_and_major_are_honest(ctx: ToolContext) -> None:
    college = call_tool(ctx, "get_college_profile", {"college_id": "zzz-9999"})
    assert college.ok is False and college.error["code"] == "COLLEGE_NOT_FOUND"
    major = call_tool(ctx, "get_major_profile", {"major_id": "zzz-9999"})
    assert major.ok is False and major.error["code"] == "MAJOR_NOT_FOUND"


def test_list_missing_fields(ctx: ToolContext) -> None:
    result = call_tool(ctx, "list_missing_fields", {})
    assert result.ok
    assert result.data["complete"] is True
    assert result.data["missing_fields"] == []


def test_unknown_tool_is_reported_not_raised(ctx: ToolContext) -> None:
    result = call_tool(ctx, "no_such_tool", {})
    assert result.ok is False and result.error["code"] == "UNKNOWN_TOOL"


def test_internal_failure_does_not_escape(ctx: ToolContext) -> None:
    """工具内部异常必须变成结果，否则 agent 循环会被一次查询失败打断。"""
    result = call_tool(ctx, "get_province_rule", {"province": "not-a-province"})
    assert result.ok is False
    assert result.error["code"] in {"NOT_FOUND", "INTERNAL_ERROR"}


# ---------------------------------------------------------------------------
# 绝不写库
# ---------------------------------------------------------------------------
def test_tool_generate_plan_does_not_write(ctx: ToolContext, session) -> None:
    """★ §9.1「绝不写库」：生成志愿表的工具只给预览。"""
    before = session.execute(select(func.count()).select_from(db.Plan)).scalar_one()
    result = call_tool(ctx, "generate_plan", {})
    assert result.ok, result.error
    assert result.data["preview"] is True
    assert result.data["persisted"] is False
    assert result.data["item_count"] > 0
    session.commit()
    after = session.execute(select(func.count()).select_from(db.Plan)).scalar_one()
    assert after == before, "工具不得写库（志愿表数量不该变化）"


def test_scan_risks_accepts_unit_ids_without_a_plan(ctx: ToolContext) -> None:
    search = call_tool(ctx, "search_units", {"province": "zhejiang", "year": CURRENT_YEAR, "limit": 2})
    unit_ids = [unit["unit_id"] for unit in search.data["units"]]
    result = call_tool(ctx, "scan_risks", {"unit_ids": unit_ids})
    assert result.ok, result.error
    assert result.data["scanned"] == len(unit_ids)
    assert isinstance(result.data["risks"], list)


def test_scan_risks_requires_something_to_scan(ctx: ToolContext) -> None:
    result = call_tool(ctx, "scan_risks", {})
    assert result.ok is False and result.error["code"] == "NOTHING_TO_SCAN"


def test_narrator_province_names_match_rule_pack() -> None:
    """叙述层的省份名必须与规则包省份一一对应（防止两边漂移）。"""
    from app.agent.narrator import PROVINCE_NAMES

    assert set(PROVINCE_NAMES) == set(PROVINCES)
