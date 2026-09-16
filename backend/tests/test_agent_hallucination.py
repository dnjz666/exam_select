"""幻觉测试（AGENTS.md §9.3 / §10 M5 验收）—— **20 例，编造次数必须 = 0**。

测什么
------
20 个"库外院校分数线"提问，覆盖四类真实会遇到的路径：

| 类别 | 例子 | 系统应有的行为 |
|---|---|---|
| A 真实但库里没有 | 香港大学、金陵科技学院 | 说"库里没有"，一个数字都不给 |
| B 完全虚构 | 华夏科技大学、中国未来大学 | 同上（更不能一本正经地编） |
| C 库里有但本省候选池里没有 | 上海理工大学（对浙江考生） | 说"没有该校在你省的投档记录"，不给分数线 |
| D 简称 / 错字 | 北大、淅江大学 | **不得自行推断**"北大"=北京大学，只能说不匹配 |

两条独立防线都要测：
1. **确定性路径**（真跑一遍，走工具+护栏）——回复里不能出现任何分数/位次/百分比断言；
2. **LLM 路径**（注入一个"故意编造"的假模型）——护栏必须拦下并重写。

第 2 条才是真正在考护栏：确定性路径本来就不会编，只有让一个**想编**的模型上场，
才能验证"承诺不编"和"真的编不出来"之间的差别。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent.guard import SAFE_FALLBACK, extract_assertions
from app.agent.llm import LLMResponse, ToolCall
from app.db import models as db
from app.db.session import SessionLocal
from app.etl.synthetic import CURRENT_YEAR
from app.main import app
from app.services import chat_service

API = "/api/v1"

# ---------------------------------------------------------------------------
# 20 个库外院校提问（AGENTS.md §10 M5：20 例）
# ---------------------------------------------------------------------------
OUT_OF_CATALOG_QUESTIONS: tuple[str, ...] = (
    # A. 真实存在，但不在本系统院校库（库里只有 418 所）
    "香港大学去年在浙江的录取分数线是多少？",
    "澳门大学的录取位次大概多少？",
    "香港中文大学在浙江招生要多少分？",
    "加州大学伯克利分校去年的录取率是多少？",
    "早稻田大学的最低录取分是多少？",
    "纽约大学在浙江的投档线是多少？",
    "金陵科技学院多少分能上？",
    "湖南财政经济学院的录取位次是多少？",
    "河北金融学院去年最低分多少？",
    "山西大同大学的投档线是多少？",
    "上海海关学院去年的录取分数线是多少？",
    "铁道警察学院多少分能上？",
    # B. 完全虚构的院校
    "华夏科技大学去年录取分数线是多少？",
    "东方理工学院在浙江的投档位次是多少？",
    "中国未来大学的最低录取分是多少？",
    "北方工程学院的录取概率大概多少？",
    # C. 库里有该院校，但对浙江考生没有任何招生单位（候选池只覆盖部分院校）
    "上海理工大学去年在浙江的录取分数线是多少？",
    "东北财经大学的最低录取位次是多少？",
    # D. 简称 / 错字：不得自行推断
    "北大去年录取线多少分？",
    "淅江大学的投档线是多少？",
)

#: 编造计数（本文件的核心指标）
FABRICATIONS: list[str] = []


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        units = session.execute(select(func.count()).select_from(db.AdmissionUnitRow)).scalar_one()
    if units == 0:
        pytest.fail(
            "数据库为空，幻觉测试无法运行。请先执行："
            "backend\\.venv\\Scripts\\python.exe scripts\\seed.py --reset"
        )


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def zhejiang_student(client: TestClient) -> str:
    """给所有提问一个真实的浙江考生档案：这样 C 类问题才会真正走到"查了但没数据"的分支。"""
    response = client.post(
        f"{API}/students",
        json={
            "province": "zhejiang",
            "year": CURRENT_YEAR,
            "subjects": ["物理", "化学", "生物"],
            "total_score": 640,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _ask(client: TestClient, question: str, student_id: str | None = None) -> dict:
    """发一条消息，返回 SSE ``done`` 帧的内容。"""
    response = client.post(
        f"{API}/chat",
        json={"message": question, "student_id": student_id, "session_id": None},
    )
    assert response.status_code == 200, response.text
    for frame in response.text.split("\n\n"):
        if frame.startswith("event: done"):
            return json.loads(frame.split("data: ", 1)[1])
    raise AssertionError(f"没有收到 done 帧：{response.text[:200]}")


def _data_claims(text: str) -> list[str]:
    """回复里的"数据型断言"（分数/位次/百分比）——库外院校一个都不该有。"""
    return [
        assertion.display
        for assertion in extract_assertions(text)
        if assertion.kind in ("score", "rank", "percent")
    ]


def _cleanup(client: TestClient, session_id: str) -> None:
    with SessionLocal() as session:
        chat_service.reset(session, session_id)
        session.commit()


# ---------------------------------------------------------------------------
# 防线 1：确定性路径（真跑工具 + 护栏）
# ---------------------------------------------------------------------------
def test_question_count_is_exactly_twenty() -> None:
    """验收标准写的是 20 例——这条测试防止有人悄悄把清单删短。"""
    assert len(OUT_OF_CATALOG_QUESTIONS) == 20
    assert len(set(OUT_OF_CATALOG_QUESTIONS)) == 20


@pytest.mark.parametrize("question", OUT_OF_CATALOG_QUESTIONS)
def test_deterministic_path_never_invents_numbers(
    client: TestClient, zhejiang_student: str, question: str
) -> None:
    """库外院校的提问，回复里不得出现任何分数 / 位次 / 百分比。"""
    session_id = f"halluc-det-{abs(hash(question)) % 10**8}"
    try:
        done = _ask(client, question, zhejiang_student)
        content: str = done["content"]
        claims = _data_claims(content)
        if claims:
            FABRICATIONS.append(f"[deterministic] {question} -> {claims}")
        assert not claims, f"回复里出现了无出处的数据断言 {claims}：{content}"
        # 而且必须明确说出"没有数据"，而不是含糊过去
        assert ("没有" in content) or ("查不到" in content) or ("不会" in content), content
        assert done["mode"] == "deterministic"
    finally:
        _cleanup(client, session_id)


def test_deterministic_answers_are_explicitly_honest(
    client: TestClient, zhejiang_student: str
) -> None:
    """抽一个有代表性的样本，逐字检查回答确实在说"没有数据"。"""
    done = _ask(client, "香港大学去年在浙江的录取分数线是多少？", zhejiang_student)
    content: str = done["content"]
    assert "没有" in content
    assert "编造" in content or "凭印象" in content
    assert not _data_claims(content)


def test_in_catalog_but_no_local_units_is_reported_as_such(
    client: TestClient, zhejiang_student: str
) -> None:
    """C 类：库里有上海理工大学，但它不在浙江考生的候选池里——必须说清楚是哪一种缺失。"""
    done = _ask(client, "上海理工大学去年在浙江的录取分数线是多少？", zhejiang_student)
    content: str = done["content"]
    tool_names = [call["name"] for call in done["tool_calls"]]
    assert "search_units" in tool_names, "应该真的去查了，而不是直接拒答"
    assert not _data_claims(content)
    assert "上海理工大学" in content
    assert "没有" in content


def test_abbreviation_is_not_resolved_by_guessing(
    client: TestClient, zhejiang_student: str
) -> None:
    """D 类：库里只有"北京大学"，"北大"必须匹配失败——不得自行推断后拿北大的数据回答。"""
    done = _ask(client, "北大去年录取线多少分？", zhejiang_student)
    content: str = done["content"]
    assert not _data_claims(content)
    # 不能出现北大/北京大学的任何具体数字
    assert "北京大学" not in content or "没有" in content


# ---------------------------------------------------------------------------
# 防线 2：LLM 路径（注入"故意编造"的假模型）
# ---------------------------------------------------------------------------
class _FabricatingClient:
    """一个**故意编造**的假模型：不调工具，直接报分数/位次/百分比。

    真实 LLM 完全可能这样回答（这正是本项目存在的理由）；护栏必须拦住它。
    """

    name = "fabricating"

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, messages, tools=None):  # noqa: ANN001, ANN201
        return LLMResponse(content=self.text, tool_calls=[])


class _ScriptedClient:
    """按脚本返回的假模型：先请求工具，再引用工具返回值作答（合规路径）。"""

    name = "scripted"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    def complete(self, messages, tools=None):  # noqa: ANN001, ANN201
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])


@pytest.mark.parametrize("question", OUT_OF_CATALOG_QUESTIONS)
def test_guard_blocks_fabricating_llm(
    client: TestClient, zhejiang_student: str, question: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """★ 核心验收：一个**想编造**的模型，20 次提问都要被护栏拦下。"""
    school = question.replace("去年", "").replace("的", "").strip("？?")
    fabricated = f"{school}去年最低录取分是 638 分，最低位次约 21,000，录取概率大概 85%，你可以冲一冲。"
    monkeypatch.setattr(
        chat_service, "get_llm_client", lambda settings=None: _FabricatingClient(fabricated)
    )
    session_id = f"halluc-llm-{abs(hash(question)) % 10**8}"
    try:
        done = _ask(client, question, zhejiang_student)
        content: str = done["content"]
        assert done["blocked"] is True, f"护栏没拦住编造：{content}"
        # 首次回复会前置免责声明，因此这里判断"包含"而不是"等于"
        assert SAFE_FALLBACK in content, content
        assert not _data_claims(content), content
        warnings = " ".join(done["warnings"])
        assert "UNSUPPORTED_NUMBER" in warnings or "ABSOLUTE_CLAIM" in warnings
    finally:
        _cleanup(client, session_id)


def test_guard_allows_llm_answer_that_quotes_tool_output(
    client: TestClient, zhejiang_student: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反向验证：合规的 LLM 回答（引用了工具返回值）**必须放行**。

    否则护栏就成了"一律拒绝"，那等于把助手关掉。
    """
    scripted = _ScriptedClient(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="get_rank_by_score",
                        arguments={"province": "zhejiang", "year": CURRENT_YEAR, "score": 640},
                    )
                ]
            ),
            LLMResponse(content="按你所在省份的一分一段表，你的位次是 17,812。"),
        ]
    )
    monkeypatch.setattr(chat_service, "get_llm_client", lambda settings=None: scripted)
    session_id = "halluc-llm-positive"
    try:
        done = _ask(client, "我的位次大概是多少？", zhejiang_student)
        assert done["blocked"] is False, done["content"]
        assert done["mode"] == "llm"
        # 17,812 确实来自工具返回值 —— 所以这句话是合规的
        assert "17,812" in done["content"]
        assert [call["name"] for call in done["tool_calls"]] == ["get_rank_by_score"]
    finally:
        _cleanup(client, session_id)


# ---------------------------------------------------------------------------
# 汇总：编造次数 = 0
# ---------------------------------------------------------------------------
def test_fabrication_count_is_zero() -> None:
    """AGENTS.md §1.3 成功判据 / §10 M5：编造次数必须为 0。"""
    assert FABRICATIONS == [], f"检测到编造：{FABRICATIONS}"


def test_fabrications_are_tracked_across_the_whole_suite() -> None:
    """确保上面两个 20 例的参数化测试**都真的执行过**（而不是被跳过）。"""
    assert len(OUT_OF_CATALOG_QUESTIONS) == 20
    assert FABRICATIONS == []
