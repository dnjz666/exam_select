"""对话端点（AGENTS.md §7 ``POST /chat`` SSE + ``GET /chat/{session_id}/history``）。

M5 起 ``/chat`` 是**真能查数据的助手**：走 ``services.chat_service`` 的 agent 编排
（工具调用 + 护栏），响应里带 ``tool_calls``，说明"这句话里的数字从哪查出来的"。

两个实现细节值得注意：
- **先算完再流式**：``respond()`` 在路由内同步跑完（含落库），``sse_frames()`` 只负责切帧。
  这样数据库会话的生命周期与请求严格对齐，也保证"没过护栏的内容绝不会被吐出去"。
- 会话历史**落库**（``chat_messages`` 表），重启不清空。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import DbDep
from app.api.schemas import ChatHistoryPayload, ChatRequest, Envelope
from app.services import chat_service

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 反向代理下禁用缓冲，保证流式
}


@router.post("/chat", summary="对话（SSE 流式，含工具调用与幻觉护栏）")
def chat(payload: ChatRequest, session: DbDep) -> StreamingResponse:
    session_id = payload.session_id or f"chat-{uuid.uuid4().hex[:12]}"
    reply = chat_service.respond(session, session_id, payload.message, payload.student_id)
    frames: Iterator[str] = chat_service.sse_frames(reply, session_id)
    return StreamingResponse(
        frames, media_type="text/event-stream", headers={**SSE_HEADERS, "X-Session-Id": session_id}
    )


@router.get(
    "/chat/{session_id}/history",
    response_model=Envelope[ChatHistoryPayload],
    summary="对话历史",
)
def chat_history(session_id: str, session: DbDep) -> Envelope[dict]:
    messages = chat_service.history(session, session_id)
    warnings: list[str] = []
    if not messages:
        warnings.append("该会话没有历史消息（换个 session_id，或先发一条消息）。")
    return Envelope[dict](
        data={"session_id": session_id, "messages": messages, "count": len(messages)},
        evidence=[],
        warnings=warnings,
    )


__all__ = ["router"]
