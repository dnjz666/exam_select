"""会话历史**定序**的回归测试（ADR-021）。

## 被修的缺陷

`chat_service._next_id()` 原先只靠 `time.time_ns()` 做时间序前缀，docstring 声称
"纳秒前缀让 id 本身就是时间序"。但 **Windows 的系统时钟粒度约 15.6ms**，
`time.time_ns()` 在同一 tick 内会返回**完全相同**的值，于是同一 tick 的两条消息
只能靠随机后缀决定先后 → **50% 概率把一问一答排成"答、问"**。

实测复现（真实落库数据）：

    assistant  msg-01790044128378781800-c9aac9   ← 同一 ns
    user       msg-01790044128378781800-e1aee5   ← 随机后缀 e1 > c9 → 助手排到了用户前面

这不是测试问题，是**用户可见的产品缺陷**：会话历史（"我当时问了什么、系统依据什么这么答"）
的顺序会错，而这段历史正是证据链的一部分。

修法：id 增加**进程内单调序号**，保证同一 tick 内也严格递增。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.db import models as db
from app.db import repositories as repo
from app.db.session import SessionLocal
from app.services import chat_service


# ---------------------------------------------------------------------------
# §1 id 必须严格递增 —— 即使时钟冻结
# ---------------------------------------------------------------------------
class TestNextIdOrdering:
    def test_ids_strictly_increase_even_with_frozen_clock(self, monkeypatch):
        """★ 核心回归：时钟冻结在同一个 tick 时，id 仍必须严格递增。

        这正是 Windows 上真实发生的情形（15.6ms 粒度），也是随机后缀唯一能"捣乱"的场景。
        """
        monkeypatch.setattr(time, "time_ns", lambda: 1_790_044_128_378_781_800)
        ids = [chat_service._next_id() for _ in range(50)]
        assert ids == sorted(ids), "时钟冻结时 id 必须仍按插入顺序递增"
        assert len(set(ids)) == len(ids), "id 必须唯一"

    def test_ids_increase_across_ticks(self, monkeypatch):
        """时钟前进时，纳秒前缀必须主导顺序。"""
        ticks = iter([1_000, 2_000, 3_000])
        monkeypatch.setattr(time, "time_ns", lambda: next(ticks))
        ids = [chat_service._next_id() for _ in range(3)]
        assert ids == sorted(ids)

    def test_id_shape_is_documented(self, monkeypatch):
        monkeypatch.setattr(time, "time_ns", lambda: 1_790_044_128_378_781_800)
        value = chat_service._next_id()
        parts = value.split("-")
        assert parts[0] == "msg"
        assert len(parts) == 4, f"id 形状应为 msg-<ns>-<seq>-<rand>，实际 {value}"
        assert len(parts[1]) == 20, "纳秒前缀必须零填充到 20 位，字典序才等于数值序"
        assert parts[2].isdigit() and len(parts[2]) == 8


# ---------------------------------------------------------------------------
# §2 落库后按 (created_at, id) 排序必须还原问答顺序
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def require_seeded_database() -> None:
    with SessionLocal() as session:
        unit = session.execute(select(db.AdmissionUnitRow).limit(1)).scalars().first()
    if unit is None:
        pytest.fail("数据库为空。请先跑 scripts/seed.py --source hybrid")


class TestStoredOrdering:
    def test_same_second_messages_keep_insertion_order(self, monkeypatch):
        """★ 端到端：把时钟冻结在同一秒同一 tick，落库后读出来的顺序必须仍是插入顺序。

        复现原缺陷需要"同一秒 + 同一 tick"；这里直接把它固定下来，所以**确定性**失败/通过，
        不再依赖运气（原缺陷在真实套件里约 1/3 概率触发）。
        """
        monkeypatch.setattr(chat_service, "_now", lambda: "2026-09-22T02:28:48+00:00")
        monkeypatch.setattr(time, "time_ns", lambda: 1_790_044_128_378_781_800)

        session_id = "test-ordering-frozen"
        with SessionLocal() as session:
            repo.delete_chat_session(session, session_id)
            session.commit()
            for role in ("user", "assistant", "user", "assistant"):
                repo.append_chat_message(
                    session,
                    message_id=chat_service._next_id(),
                    session_id=session_id,
                    role=role,
                    content=f"{role} 内容",
                )
            session.commit()

            rows = repo.list_chat_messages(session, session_id)
            assert [r.role for r in rows] == ["user", "assistant", "user", "assistant"]

            # 收尾：不留脏数据
            repo.delete_chat_session(session, session_id)
            session.commit()

    def test_ordering_survives_many_messages_in_one_tick(self, monkeypatch):
        """同一 tick 内写很多条（远超一次会话的规模），顺序仍必须正确。"""
        monkeypatch.setattr(chat_service, "_now", lambda: "2026-09-22T02:28:48+00:00")
        monkeypatch.setattr(time, "time_ns", lambda: 1_790_044_128_378_781_800)

        session_id = "test-ordering-many"
        expected = ["user", "assistant"] * 15
        with SessionLocal() as session:
            repo.delete_chat_session(session, session_id)
            session.commit()
            for role in expected:
                repo.append_chat_message(
                    session,
                    message_id=chat_service._next_id(),
                    session_id=session_id,
                    role=role,
                    content="x",
                )
            session.commit()
            rows = repo.list_chat_messages(session, session_id)
            assert [r.role for r in rows] == expected
            repo.delete_chat_session(session, session_id)
            session.commit()
