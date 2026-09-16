"""幻觉护栏单测（AGENTS.md §9.3）。

护栏是全项目的最后一道闸门，因此它需要**两个方向**的测试：

- **拦得住**：工具没返回过的数字、绝对化承诺 → 必须拦截并重写；
- **不误伤**：合规引用、正当建议、模式名称、年份、量词 → 必须放行。

只测"拦得住"是不够的：一个总在误拦的护栏，最后一定会被人关掉，
那比没有护栏更糟——因为它会给人"有防护"的错觉。
"""

from __future__ import annotations

import pytest

from app.agent.guard import (
    SAFE_FALLBACK,
    ToolCallRecord,
    collect_numbers,
    extract_assertions,
    find_absolute_claims,
    guard_response,
)


def _rank_tool(rank: int) -> ToolCallRecord:
    return ToolCallRecord(
        name="get_rank_by_score", arguments={"score": 640}, result={"data": {"rank": rank}}
    )


# ---------------------------------------------------------------------------
# 拦得住
# ---------------------------------------------------------------------------
def test_blocks_fabricated_score() -> None:
    """经典反例（§9.2）：编造分数线 + 伪精确。"""
    reply = "浙江大学去年录取线 660 分，你考了 655，差一点点，可以冲一冲。"
    result = guard_response(reply, [_rank_tool(17812)])
    assert result.allowed is False
    assert "UNSUPPORTED_NUMBER" in result.codes
    assert result.reply == SAFE_FALLBACK, "拦截后必须重写成安全文案"


def test_blocks_fabricated_rank_and_percent() -> None:
    reply = "你的位次是 12,340，录取概率 73%。"
    result = guard_response(reply, [_rank_tool(17812)])
    assert result.allowed is False
    assert result.codes.count("UNSUPPORTED_NUMBER") == 2  # 位次与百分比各一处


def test_allows_numbers_that_came_from_tools() -> None:
    reply = "你的位次是 12,340，对应的百分位是 4.39%。"
    result = guard_response(
        reply,
        [
            ToolCallRecord(
                name="get_rank_by_score",
                result={"data": {"rank": 12340, "percentile": 0.0439}},
            )
        ],
    )
    assert result.allowed is True, result.violations


def test_percent_matches_probability_scale() -> None:
    """工具给 0.62，回复写 62% 是同一件事——不能因为量纲不同就拦掉。"""
    records = [ToolCallRecord(name="estimate_probability", result={"data": {"probability": 0.62}})]
    assert guard_response("录取概率约 62%。", records).allowed is True
    assert guard_response("录取概率约 91%。", records).allowed is False


def test_rounding_tolerance_is_bounded() -> None:
    records = [ToolCallRecord(name="x", result={"data": {"min_rank": 12340}})]
    assert guard_response("最低位次 12,340。", records).allowed is True
    assert guard_response("最低位次 12,340.4。", records).allowed is True  # 展示四舍五入
    assert guard_response("最低位次 12,300。", records).allowed is False  # 差 40，不算容差


def test_blocks_absolute_claims() -> None:
    for reply in (
        "服从调剂就保证录取。",
        "你这个分数一定能上。",
        "这样填百分百没问题。",
        "这个志愿稳上。",
        "不服从调剂也绝对不会退档。",
    ):
        result = guard_response(reply, [])
        assert result.allowed is False, reply
        assert "ABSOLUTE_CLAIM" in result.codes, reply


def test_blocks_number_hidden_in_a_url_like_string() -> None:
    """★ 后门检查：白名单只收结构的数值字段，绝不从字符串里抓数字。

    否则 ``source_url`` 里的年份、``unit_id`` 里的专业代码都会变成"合法数字"，
    编造的 2026 分正好能撞上 URL 里的 2026。
    """
    record = ToolCallRecord(
        name="get_unit_history",
        result={"data": {"source_url": "https://www.zjzs.net/art/2026/6/13/art_156_12376.html"}},
    )
    assert collect_numbers(record.result) == set()
    assert guard_response("该单位最低分 12376 分。", [record]).allowed is False


# ---------------------------------------------------------------------------
# 不误伤
# ---------------------------------------------------------------------------
def test_allows_years_and_model_names() -> None:
    reply = "浙江是 3+3 模式，2026 年实行 7 选 3，选考科目要求分 all_of 与 any_of 两种。"
    assert guard_response(reply, []).allowed is True, extract_assertions(reply)


def test_allows_normal_advice_containing_the_word_yiding() -> None:
    """「一定」单独出现是正常建议，只有与录取结果绑定才是承诺。"""
    for reply in (
        "填报时一定要留足保底志愿。",
        "我建议你一定要核对招生章程里的体检要求。",
        "顺序志愿下第一志愿一定要放最想去的。",
    ):
        assert guard_response(reply, []).allowed is True, reply


def test_allows_small_quantifiers() -> None:
    """「3 门」「1 个」这类量词不是数据断言（实测：过宽的窗口会把它们判成分数）。"""
    reply = "你的档案还缺这几项：省份、选考科目（恰好 3 门）、高考总分。"
    assert guard_response(reply, []).allowed is True
    assert find_absolute_claims(reply) == []


def test_allows_volunteer_cap_only_when_sourced() -> None:
    sourced = [ToolCallRecord(name="get_province_rule", result={"data": {"max_volunteers": 80}})]
    assert guard_response("这个批次最多填 80 个志愿。", sourced).allowed is True
    assert guard_response("这个批次最多填 80 个志愿。", []).allowed is False


def test_known_facts_allow_the_students_own_numbers() -> None:
    """考生自己的分数/位次是系统确认过的事实，回显它们不是编造。"""
    facts = {"total_score": 640, "rank": 12340}
    assert guard_response("你的总分 640，位次 12,340。", [], known_facts=facts).allowed is True
    assert guard_response("你的总分 655。", [], known_facts=facts).allowed is False


def test_safe_fallback_itself_passes_the_guard() -> None:
    """兜底文案自己必须合规——否则拦截会变成死循环。"""
    assert guard_response(SAFE_FALLBACK, []).allowed is True


# ---------------------------------------------------------------------------
# 提取器
# ---------------------------------------------------------------------------
def test_extract_assertions_classifies_by_context() -> None:
    reply = "2026 年最低分 660，最低位次 12,340，计划 20 人，概率 62%，最多填 80 个志愿。"
    kinds = {assertion.kind for assertion in extract_assertions(reply)}
    assert kinds == {"score", "rank", "plan_count", "percent", "volunteer_cap"}
    # 2026 是年份，不是数据断言
    assert all(assertion.raw != "2026" for assertion in extract_assertions(reply))


def test_collect_numbers_walks_nested_structures() -> None:
    payload = {
        "a": 1,
        "b": [2, {"c": 3.5}],
        "d": "12376",  # 纯数字字符串：接受
        "e": "https://x/2026/y",  # 含数字但不是纯数字：拒绝
        "f": True,  # bool 不是数字
        "g": None,
    }
    assert collect_numbers(payload) == {1.0, 2.0, 3.5, 12376.0}


def test_empty_reply_is_allowed() -> None:
    assert guard_response("", []).allowed is True


@pytest.mark.parametrize(
    "reply",
    [
        "浙江大学的投档位次近三年是 9,800 / 10,200 / 9,950（来源：浙江省教育考试院）。",
        "服从调剂可以显著降低退档风险，但不构成录取承诺。",
    ],
)
def test_representative_good_answers(reply: str) -> None:
    """§9.2 的正例：引用了来源、没有绝对化表述。"""
    records = [
        ToolCallRecord(name="get_unit_history", result={"data": {"ranks": [9800, 10200, 9950]}})
    ]
    assert guard_response(reply, records).allowed is True
