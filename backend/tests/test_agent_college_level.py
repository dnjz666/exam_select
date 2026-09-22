"""院校层次问答的端到端测试（ADR-019）。

★ 为什么单独建文件：这个缺陷是"工具**注册了**但**走不到**" ——
`get_college_level_facts` 一开始只加进了 `tools.py`，而默认走的是
**确定性路径**（`LLM_PROVIDER=none`），`parser.detect_intent` 里没有对应意图，
于是"浙江工业大学怎么样"落到 `unknown`、被当成"问分数线"回答。
工具存在 ≠ 功能可用 —— 必须用**真实问答**守住。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agent.narrator import narrate_college_level
from app.db import models as db
from app.db.session import SessionLocal
from app.etl.synthetic import CURRENT_YEAR
from app.services import chat_service


@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        unit = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
    if unit is None:
        pytest.fail("数据库为空，层次问答测试无法运行。请先跑 scripts/seed.py --source hybrid")


@pytest.fixture()
def session():
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def student(session):
    row = (
        session.query(db.Student)
        .filter(db.Student.province == "zhejiang")
        .first()
    )
    if row is None:
        pytest.fail("库里没有浙江考生档案")
    return row


def _ask(session, student, message: str, session_id: str = "test-level") -> str:
    reply = chat_service.respond(
        session, student_id=student.id, message=message, session_id=session_id
    )
    return reply.content or ""


# ---------------------------------------------------------------------------
# §1 问"怎么样"必须给层次判据，而不是一串位次数字
# ---------------------------------------------------------------------------
class TestLevelQuestion:
    def test_level_question_answers_with_basis_not_scores(self, session, student):
        text = _ask(session, student, "浙江工业大学怎么样")
        assert "层次" in text
        # 必须出现判据与来源，而不是只有分数线
        assert "省重点建设高校" in text or "层次标签" in text
        assert "来源" in text

    def test_level_question_does_not_hijack_history_questions(self, session, student):
        """★ 回归：问"分数线"仍必须答历史位次。"""
        text = _ask(session, student, "浙江工业大学分数线")
        assert "投档情况" in text or "最低位次" in text
        assert "层次判据" not in text

    def test_level_answer_states_tags_are_not_the_only_standard(self, session, student):
        """★ 核心认知：没有 985/211 标签 ≠ 层次低。"""
        text = _ask(session, student, "浙江工业大学算不算好学校")
        assert "不等于层次低" in text

    def test_level_answer_refuses_ranking(self, session, student):
        """★ 红线：不得给排名。"""
        text = _ask(session, student, "浙江工业大学什么水平")
        assert "不是" in text and "排名" in text  # 明确声明"不是该校排名"
        assert "排第几" in text

    def test_unknown_school_is_honest(self, session, student):
        text = _ask(session, student, "霍格沃茨大学怎么样")
        assert "没有" in text and ("编造" in text or "给不出" in text)


# ---------------------------------------------------------------------------
# §2 叙述器只转述，不新增判断
# ---------------------------------------------------------------------------
class TestNarratorLevel:
    BASE = {
        "name": "示例大学",
        "province": "zhejiang",
        "city": "杭州",
        "level_tags": [],
        "affiliation": "省重点建设高校",
        "is_public": True,
        "level_score": 0.60,
        "level_basis": "无 985/211/双一流标签，但隶属/属性为「省重点建设高校」→ 0.60（省重点/部属档）",
        "region_strength": 3 / 31,
        "region_top_college_count": 3,
        "region_top_college_count_max": 31,
        "is_home_province": True,
        "caveats": ["没有标签不等于层次低"],
        "note": "两者都不是对单所院校的排名；不得引申为「这所学校排第几」。",
    }

    def test_transcribes_basis_and_caveats(self):
        text = narrate_college_level(self.BASE)
        assert "0.60" in text
        assert "省重点建设高校" in text
        assert "没有标签不等于层次低" in text

    def test_province_is_rendered_in_chinese(self):
        """省份必须显示中文，不能把内部键 `zhejiang` 直接抛给考生。"""
        text = narrate_college_level(self.BASE)
        assert "浙江" in text
        assert "zhejiang" not in text

    def test_region_strength_is_labelled_as_not_a_ranking(self):
        text = narrate_college_level(self.BASE)
        assert "高教资源密度" in text
        assert "不是" in text and "排名" in text

    def test_denominator_comes_from_payload_not_hardcoded(self):
        """★ 归一化分母必须来自工具返回值。

        实测被测试抓到：叙述器原先**硬编码** `/ 31`，那是把领域常量偷偷搬进了展示层。
        """
        text = narrate_college_level(self.BASE)
        assert "/ 31" in text
        # 换一个分母，输出必须跟着变（证明不是写死的）
        other = narrate_college_level({**self.BASE, "region_top_college_count_max": 99})
        assert "/ 99" in other
        assert "/ 31" not in other

    def test_no_invented_numbers(self):
        """★ 输出里的数字只能是**载荷里已有**的数字，或是它们的**四舍五入显示**。

        `985`/`211` 也在这条规则的射程内 —— 它们来自工具给的 `level_basis` 文本，
        属于"已提供"。`0.10` 是 `0.0967…` 的两位小数显示，同属合法格式化。
        """
        import json
        import re

        payload_text = json.dumps(self.BASE, ensure_ascii=False)
        raw = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", payload_text)}
        allowed = {f"{value:.2f}" for value in raw} | {f"{value:.1f}" for value in raw}
        allowed |= {n for n in re.findall(r"\d+(?:\.\d+)?", payload_text)}

        produced = set(re.findall(r"\d+(?:\.\d+)?", narrate_college_level(self.BASE)))
        assert produced <= allowed, f"叙述器引入了载荷里没有的数字：{produced - allowed}"

    def test_private_college_warns_about_tuition(self):
        payload = dict(self.BASE)
        payload.update(
            {
                "is_public": False,
                "affiliation": None,
                "level_score": 0.20,
                "level_basis": "民办 / 独立学院 → 0.20",
                "caveats": ["民办/独立学院：学费通常显著高于公办，必须在推荐卡片上明示（名师铁律 10）。"],
            }
        )
        text = narrate_college_level(payload)
        assert "民办" in text
        assert "学费" in text

    def test_home_province_note_only_when_home(self):
        home = narrate_college_level(self.BASE)
        assert "本省" in home
        away = narrate_college_level({**self.BASE, "is_home_province": False})
        assert "本省" not in away
