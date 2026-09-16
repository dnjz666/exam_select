"""LLM 客户端（AGENTS.md §4.1：provider 可插拔、必须可替换、可 mock）。

设计约束
--------
- **可插拔**：``LLMClient`` 是协议；``llm_provider`` 决定用哪个实现。
  新增一个 provider = 加一个类 + 注册一行，不动 agent 其余部分。
- **可 mock**：测试通过依赖注入传自己的实现（见 ``tests/test_agent_hallucination.py``），
  因此**任何测试都不需要外网、不需要 API key**。
- **可以没有 LLM**：``get_llm_client()`` 返回 ``None`` 时，``/chat`` 走
  ``app/agent/parser.py`` 的确定性路径。这不是"降级玩具"——
  没有 LLM 时系统的每一个数字仍然来自工具、每句话仍然过护栏。

为什么用标准库 ``urllib`` 而不是 httpx
------------------------------------
这里只有一个 POST，且必须是**运行时**依赖。多引入一个 HTTP 客户端 =
多一份供应链与版本面，收益却只是一个请求。真需要连接池/重试时再换，接口不变。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import Settings, get_settings


class LLMError(Exception):
    """LLM 调用失败（网络/鉴权/协议）。**绝不**在失败时编造一个回答。"""


@dataclass(frozen=True)
class ToolCall:
    """模型请求的一次工具调用。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """一次模型回复：要么是文本，要么是工具调用（也可能两者都有）。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""


@runtime_checkable
class LLMClient(Protocol):
    """provider 协议。实现它即可接入任意 OpenAI 兼容服务。"""

    name: str

    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


class OpenAICompatibleClient:
    """OpenAI 兼容的 ``/chat/completions`` 客户端（DeepSeek / Qwen / vLLM… 同理）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        temperature: float = 0.2,
    ) -> None:
        self.name = "openai-compatible"
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # 4xx/5xx：把后端原文带出来，便于排错
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM 返回 HTTP {exc.code}：{detail}") from None
        except urllib.error.URLError as exc:
            raise LLMError(f"连接 LLM 失败：{exc.reason}") from None
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM 响应不可解析：{exc}") from None

        return _parse_openai_response(body)


def _parse_openai_response(body: dict[str, Any]) -> LLMResponse:
    choices = body.get("choices") or []
    if not choices:
        raise LLMError(f"LLM 响应没有 choices：{str(body)[:200]}")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content") or ""
    calls: list[ToolCall] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        name = function.get("name") or ""
        if not name:
            continue
        arguments: dict[str, Any] = {}
        raw_args = function.get("arguments")
        if isinstance(raw_args, str) and raw_args.strip():
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    arguments = parsed
            except json.JSONDecodeError:
                # 模型给出非法 JSON：当作空参数，让工具自己报"缺参数"，
                # 而不是让整轮对话崩掉
                arguments = {}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        calls.append(ToolCall(id=str(raw.get("id") or f"call-{index}"), name=name, arguments=arguments))
    return LLMResponse(content=content, tool_calls=calls, model=str(body.get("model") or ""))


def get_llm_client(settings: Settings | None = None) -> LLMClient | None:
    """按配置构造客户端；未配置 provider/key 时返回 ``None``（走确定性路径）。"""
    settings = settings or get_settings()
    if not settings.llm_enabled:
        return None
    if settings.llm_provider != "openai":
        raise LLMError(
            f"未知的 llm_provider：{settings.llm_provider}（可选：none | openai）。"
            "新增 provider 请实现 LLMClient 协议并在此注册。"
        )
    return OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )


__all__ = [
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "OpenAICompatibleClient",
    "ToolCall",
    "get_llm_client",
]
