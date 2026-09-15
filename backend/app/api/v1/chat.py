"""对话端点（AGENTS.md §7 ``POST /chat`` SSE + ``GET /chat/{session_id}/history``）。

⚠️ **M3 范围**：交付可用的 SSE 通道与会话历史；LLM 工具调用 / System Prompt /
输出护栏（guard）属于 **M5**（§9）。当前回复**不含任何数字**（§0 最高原则），
首次回复含免责声明（§12）。
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


@router.post("/chat", summary="对话（SSE 流式）")
def chat(payload: ChatRequest, session: DbDep) -> StreamingResponse:
    session_id = payload.session_id or f"chat-{uuid.uuid4().hex[:12]}"
    generator: Iterator[str] = chat_service.stream(
        session, session_id, payload.message, payload.student_id
    )
    return StreamingResponse(
        generator, media_type="text/event-stream", headers={**SSE_HEADERS, "X-Session-Id": session_id}
    )


@router.get(
    "/chat/{session_id}/history",
    response_model=Envelope[ChatHistoryPayload],
    summary="对话历史",
)
def chat_history(session_id: str) -> Envelope[dict]:
    messages = chat_service.history(session_id)
    warnings: list[str] = []
    if not messages:
        warnings.append("该会话没有历史消息（M3 的会话历史存内存，重启后清空；M5 落库）。")
    return Envelope[dict](
        data={"session_id": session_id, "messages": messages, "count": len(messages)},
        evidence=[],
        warnings=warnings,
    )


__all__ = ["router"]
