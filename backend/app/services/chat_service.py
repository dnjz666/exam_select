"""对话编排（L4，AGENTS.md §7 ``POST /chat`` SSE + ``GET /chat/{id}/history``）。

⚠️ **M3 范围**：交付**可用的 SSE 通道、会话历史与防幻觉底线**；
LLM 工具调用 / System Prompt / guard 输出校验器属于 **M5**（§9）。

本模块在 M3 就强制三条底线（§0 最高原则、§3.3、§12）：
1. **不产生任何数字**：分数线、位次、录取率、计划数一律不得出现在回复里——
   这些只能来自工具调用（M5）；M3 的回复明确告知"数字请以推荐页/报告为准"。
2. **不替考生假设**：缺字段就追问（一次最多 3 个，§9.2）。
3. **首次回复必须含免责声明**（§12）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db import repositories as repo

DISCLAIMER = (
    "本系统输出仅供参考，最终以各省考试院官方文件与招生章程为准；"
    "当前数据为模拟数据，严禁用于真实填报。"
)

#: 会话历史存内存（M3 单进程 dev）；M5 接入 LLM 后改为落库（见 DATA_DICTIONARY §7）
_SESSIONS: dict[str, list[dict]] = {}
_MESSAGE_SEQ = 0


@dataclass
class ChatReply:
    session_id: str
    content: str
    missing_fields: list[str] = field(default_factory=list)
    first_reply: bool = False


def _next_id() -> str:
    global _MESSAGE_SEQ
    _MESSAGE_SEQ += 1
    return f"msg-{_MESSAGE_SEQ:06d}"


def history(session_id: str) -> list[dict]:
    return list(_SESSIONS.get(session_id, ()))


def append(session_id: str, role: str, content: str, **meta: object) -> dict:
    message = {
        "id": _next_id(),
        "session_id": session_id,
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        **meta,
    }
    _SESSIONS.setdefault(session_id, []).append(message)
    return message


def build_reply(session: Session | None, student_id: str | None) -> ChatReply:
    """生成合规回复：**不含任何数字断言**，缺字段先追问。"""
    missing: list[str] = []
    if student_id and session is not None:
        row = repo.get_student(session, student_id)
        if row is None:
            missing = ["province", "subjects", "total_score"]
        else:
            from app.db import repositories as _repo

            missing = list(_repo.row_to_student(row).missing_fields)
    else:
        missing = ["province", "subjects", "total_score"]

    labels = {
        "province": "省份",
        "subjects": "选考科目（3+3 需恰好 3 门）",
        "total_score": "高考总分",
        "rank": "位次（可选：填了总分可自动换算）",
    }
    lines: list[str] = []
    if missing:
        asked = missing[:3]  # 一次最多问 3 个（§9.2）
        lines.append("要给你靠谱的志愿建议，我还缺几个关键信息：")
        lines.extend(f"{index}. {labels.get(field, field)}" for index, field in enumerate(asked, start=1))
        lines.append("请在「建档向导」补齐后回到推荐页，我才能基于真实数据算给你看。")
    else:
        lines.append(
            "你的档案已经齐全。推荐结果与每一条依据都在推荐页的「为什么」里，"
            "数字我只转述系统算出来的结果，不会凭印象报给你。"
        )
    lines.append(
        "说明：完整的对话式工具调用（查位次、查历史、跑概率）在 M5 交付；"
        "在此之前，任何分数线、位次、录取率都不会由我口头给出——宁可不答，不可编造。"
    )
    return ChatReply(session_id="", content="\n".join(lines), missing_fields=missing)


def stream(session: Session | None, session_id: str, message: str, student_id: str | None = None) -> Iterator[str]:
    """SSE 流：``start`` → 逐段 ``delta`` → ``done``（含完整回复与追问字段）。"""
    is_first = not history(session_id)
    append(session_id, "user", message, student_id=student_id)
    reply = build_reply(session, student_id)
    reply.session_id = session_id
    reply.first_reply = is_first

    preface = f"{DISCLAIMER}\n\n" if is_first else ""
    yield _frame("start", {"session_id": session_id, "first_reply": is_first, "disclaimer": DISCLAIMER if is_first else None})
    for chunk in _chunks(preface + reply.content):
        yield _frame("delta", {"text": chunk})
    stored = append(
        session_id,
        "assistant",
        preface + reply.content,
        missing_fields=reply.missing_fields,
        note="M3 文本回复（不含数字）；工具化回答见 M5",
    )
    yield _frame(
        "done",
        {
            "message_id": stored["id"],
            "content": stored["content"],
            "missing_fields": reply.missing_fields,
        },
    )


def _chunks(text: str, size: int = 24) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


def _frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def reset() -> None:
    """测试用：清空内存会话。"""
    _SESSIONS.clear()


__all__ = ["DISCLAIMER", "ChatReply", "append", "build_reply", "history", "reset", "stream"]
