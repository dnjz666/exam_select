"""自然语言解析单测（AGENTS.md §9.2 / §3.3）。

解析器的验收标准只有一条：**只抽明确说出的，抽不到就追问**。
因此这里既测"抽得准"，也测"没说的绝不补"。
"""

from __future__ import annotations

import pytest

from app.agent.parser import (
    build_questions,
    detect_intent,
    find_named_entity,
    find_subjects,
    parse_profile_fields,
)


# ---------------------------------------------------------------------------
# 字段抽取
# ---------------------------------------------------------------------------
def test_parses_province_score_rank_and_exam() -> None:
    parsed = parse_profile_fields("我是浙江考生，选了物理化学生物，考了640分，位次12340，色弱")
    assert parsed.fields["province"] == "zhejiang"
    assert parsed.fields["total_score"] == 640
    assert parsed.fields["rank"] == 12340
    assert parsed.subjects == ["物理", "化学", "生物"]
    assert parsed.physical_exam == {"color_weakness": True}


def test_parses_gender_and_language() -> None:
    parsed = parse_profile_fields("我是女生，外语考的是日语，身高165")
    assert parsed.fields["gender"] == "女"
    assert parsed.fields["foreign_language"] == "日语"
    assert parsed.physical_exam["height_cm"] == 165


def test_normalises_subject_aliases_to_plan_wording() -> None:
    """官方行文"生物/生物学""政治/思想政治"并存，必须归一到招生计划口径。"""
    assert find_subjects("我选了生物学、政治、通用技术") == ["生物", "思想政治", "技术"]


def test_extracts_major_intent_only_from_explicit_trigger() -> None:
    """★ 回归：不能把**选考科目**当成专业意向。

    早期用关键词表实现时，"我选了物理化学生物，想学计算机" 会把"物理"也当成志愿意向。
    """
    parsed = parse_profile_fields("我选了物理化学生物，想学计算机")
    assert parsed.preferences["intended_major_categories"] == ["计算机"]


def test_extracts_major_intent_with_suffix() -> None:
    """专业意向能带"专业"后缀识别。

    ★ ADR-022：学费预算已移除，因此"学费不超过 8000"这类说法**不再**被解析
    （没有字段可写）。这里同时钉住这一点，防止以后有人把它加回来。
    """
    parsed = parse_profile_fields("想读临床医学专业，学费不超过8000")
    assert parsed.preferences["intended_major_categories"] == ["临床医学"]
    assert "budget_max" not in parsed.preferences
    assert "budget_comfortable" not in parsed.preferences


def test_missing_fields_are_not_invented() -> None:
    """什么都不说 → 什么都不抽（绝不替考生假设）。"""
    parsed = parse_profile_fields("帮我看看志愿")
    assert parsed.is_empty()
    assert parsed.subjects == []


def test_partial_input_only_fills_what_was_said() -> None:
    parsed = parse_profile_fields("我是上海考生")
    assert parsed.fields == {"province": "shanghai"}
    assert "total_score" not in parsed.fields


@pytest.mark.parametrize(
    "text",
    [
        "上海大学的最低录取位次是多少？",
        "北京师范大学多少分能上？",
        "天津大学去年录取线多少？",
        "山东大学的投档线是多少？",
        "浙江大学怎么样？",
        "海南大学去年录取分数线是多少？",
        "南京大学的最低录取位次是多少？",
    ],
)
def test_school_name_is_not_mistaken_for_student_province(text: str) -> None:
    """★ 回归：校名里天然带省份，**绝不能**被当成"考生在哪个省"。

    实测踩过：问一句"上海大学的最低录取位次是多少"，考生档案的省份就被改成了上海，
    随之整套推荐都换了规则——这是很严重的一类错误。
    """
    parsed = parse_profile_fields(text)
    assert "province" not in parsed.fields, f"{text} → {parsed.fields}"


def test_student_province_still_detected_when_school_also_mentioned() -> None:
    """校名剥掉后，真正的"我是浙江考生"仍然要能识别。"""
    parsed = parse_profile_fields("我是浙江考生，想报上海大学")
    assert parsed.fields.get("province") == "zhejiang"


# ---------------------------------------------------------------------------
# 追问
# ---------------------------------------------------------------------------
def test_build_questions_limits_to_three() -> None:
    """§9.2：一次最多问 3 个问题。"""
    questions = build_questions(["province", "subjects", "total_score", "rank"])
    assert len(questions) == 3
    assert all(question.endswith(("？", "。", "说。")) or "？" in question for question in questions)


def test_build_questions_ignores_unknown_fields() -> None:
    assert build_questions(["not_a_field"]) == []


# ---------------------------------------------------------------------------
# 意图
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好", "greeting"),
        ("帮我看看档案还缺什么", "missing"),
        ("浙江最多能填几个志愿？有没有调剂？", "rule"),
        ("服从调剂会不会被退档，有什么风险", "risk"),
        ("什么是院校专业组", "concept"),
        ("查一下合肥工业大学的投档历史", "history"),
        ("清华大学去年录取线多少分", "history"),
        ("帮我推荐一些学校", "recommend"),
        # ★ 回归：句子里带"位次"但问的是推荐，不能被 rank 抢走
        ("我这个位次能报什么学校", "recommend"),
        ("帮我把分数换算成位次", "rank"),
        ("谢谢", "thanks"),
        ("今天天气不错", "unknown"),
        # ★ ADR-019：院校层次/实力类问题必须与"多少分"分流
        ("浙江工业大学怎么样", "college_level"),
        ("浙江工业大学算不算好学校", "college_level"),
        ("杭州电子科技大学什么水平", "college_level"),
        ("这所学校实力如何", "college_level"),
        ("浙工大值得报吗", "college_level"),
        # ★ 回归：问分数/历史仍是 history，不能被 college_level 抢走
        ("浙江工业大学分数线", "history"),
        ("浙江工业大学去年录取线多少分", "history"),
        # ★ 回归：问志愿规则仍是 rule
        ("浙江最多能填几个志愿", "rule"),
    ],
)
def test_detect_intent(text: str, expected: str) -> None:
    assert detect_intent(text) == expected


# ---------------------------------------------------------------------------
# 实体匹配
# ---------------------------------------------------------------------------
def test_find_named_entity_prefers_longest_match() -> None:
    names = [("a", "北京大学"), ("b", "大学"), ("c", "中国人民大学")]
    assert find_named_entity("我想去中国人民大学", names) == ("c", "中国人民大学")
    assert find_named_entity("北京大学怎么样", names) == ("a", "北京大学")


def test_find_named_entity_returns_none_when_absent() -> None:
    """简称不匹配 → 返回 None → 上层必须说"库里没有"，**不得自行推断"北大"=北京大学**。"""
    names = [("a", "北京大学")]
    assert find_named_entity("北大怎么样", names) is None
    assert find_named_entity("淅江大学怎么样", names) is None  # 错字
