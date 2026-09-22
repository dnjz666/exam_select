"""对话编排（L5 agent 层，AGENTS.md §9 / §10 M5）。

两条路径，**同一个底线**
----------------------
- **LLM 路径**（配置了 ``LLM_PROVIDER`` + key 时）：System Prompt 约束 + 工具调用 + 护栏后置校验。
- **确定性路径**（默认）：``parser`` 判意图 → ``tools`` 查数据 → ``narrator`` 说人话 → ``guard`` 校验。
  没有 LLM 也能用，而且是**零编造**的：每个数字都来自工具，每句话都过护栏。

两条路径产出的文本都要过 :func:`app.agent.guard.guard_response`；
响应里带上 ``tool_calls``，让"这句话里的数字从哪来"可回溯。

为什么"对话式建档"由**确定性 parser** 负责写库，而不是让 LLM 决定
--------------------------------------------------------------
考生说"我浙江的，选物化生，考了 640"，这是**考生自述的事实**，不是模型的判断。
用规则抽字段（抽不到就追问）既不会猜错，也不会被模型的自由发挥带偏；
LLM 在 M5 里始终只负责"解释与追问"，不负责往库里写数据。
"""

from __future__ import annotations

import itertools
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agent import narrator, prompts
from app.agent.guard import GuardResult, ToolCallRecord, guard_response
from app.agent.llm import LLMClient, LLMError, get_llm_client
from app.agent.parser import (
    ParsedProfile,
    build_questions,
    detect_intent,
    find_school_mention,
    parse_profile_fields,
)
from app.agent.tools import TOOL_SCHEMAS, ToolContext, ToolResult, call_tool
from app.config import get_settings
from app.db import models as db
from app.db import repositories as repo
from app.etl.synthetic import CURRENT_YEAR
from app.services import student_service

DISCLAIMER = (
    "本系统输出仅供参考，最终以各省考试院官方文件与招生章程为准；"
    "当前数据为模拟数据，严禁用于真实填报。"
)

#: 喂给 LLM 的历史窗口（完整历史仍可从库里取）
HISTORY_WINDOW = 12


@dataclass
class AgentReply:
    """一轮对话的完整结果（文本 + 证据 + 状态）。"""

    content: str
    tool_calls: list[dict] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    mode: str = "deterministic"
    blocked: bool = False
    warnings: list[str] = field(default_factory=list)
    applied_fields: dict[str, Any] = field(default_factory=dict)
    #: 本轮结束时的档案 id。**对话式建档时前端必须据此更新自己的 studentId**，
    #: 否则下一条消息又会被当成"还没有档案"，重复建档。
    student_id: str | None = None


#: 进程内单调递增序号 —— 与 ``time.time_ns()`` 一起构成**严格递增**的消息 id。
#: 为什么不能只靠纳秒：Windows 的系统时钟粒度约 15.6ms，``time.time_ns()`` 在同一 tick 内
#: 会返回**完全相同**的值，于是同 tick 的两条消息只能靠随机后缀决定先后 → 一问一答被排成
#: "答、问"（实测复现：``msg-01790044128378781800-c9aac9`` 与 ``...-e1aee5`` 同 ns）。
_MSG_SEQ = itertools.count(1)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _next_id() -> str:
    """**严格可按字典序排序**的消息 id：``msg-<纳秒>-<进程内序号>-<随机后缀>``。

    会话历史按 ``(created_at, id)`` 排序，而 ``created_at`` 只精确到秒，
    同一秒里的多条消息只能靠 id 决定先后。因此 id 必须**严格递增**：

    * **纳秒前缀**：跨 tick 时天然有序（20 位零填充，字典序 == 数值序）；
    * **进程内序号**：★ 同一 tick 内纳秒会**完全相同**（Windows 时钟粒度 ~15.6ms），
      只靠纳秒 + 随机后缀会让先后变成 50% 抛硬币 —— 实测复现过
      "assistant 排在 user 前面"，导致会话历史一问一答错位。
      序号保证同 tick 内也严格递增；
    * **随机后缀**：仅保证唯一，不参与时序判断。

    > 跨进程（多 worker）并发写同一会话仍有理论上的定序歧义 —— 那属于分布式定序问题，
    > 本系统单 worker 部署，不引入额外机制。
    """
    return f"msg-{time.time_ns():020d}-{next(_MSG_SEQ):08d}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# 会话事实（给 prompts / guard 用的"已知事实"）
# ---------------------------------------------------------------------------
def build_facts(session: Session, student_id: str | None) -> dict[str, Any]:
    """当前会话已知的考生事实。**这些是系统确认过的数据**，模型可以直接引用。"""
    facts: dict[str, Any] = {"student_id": student_id}
    if not student_id:
        facts["missing_fields"] = ["province", "subjects", "total_score"]
        return facts
    row = repo.get_student(session, student_id)
    if row is None:
        facts["missing_fields"] = ["province", "subjects", "total_score"]
        return facts
    profile = repo.row_to_student(row)
    facts.update(
        {
            "province": profile.province,
            "subjects": list(profile.subjects),
            "total_score": profile.total_score,
            "rank": profile.rank,
            "missing_fields": list(profile.missing_fields),
        }
    )
    return facts


# ---------------------------------------------------------------------------
# 对话式建档：确定性 parser 抽字段 → 写入草稿（不替考生假设）
# ---------------------------------------------------------------------------
def _apply_parsed_profile(
    session: Session, student_id: str | None, parsed: ParsedProfile
) -> tuple[str | None, dict[str, Any]]:
    """把考生**明确说出**的字段写进档案草稿，返回 ``(student_id, 已写入字段)``。"""
    payload: dict[str, Any] = {}
    if parsed.fields:
        payload.update(parsed.fields)
    # 选考必须恰好 3 门才写入：多一门少一门都是非法档案，宁可先追问
    if parsed.subjects and len(parsed.subjects) == 3:
        payload["subjects"] = parsed.subjects
    if parsed.preferences:
        payload["preferences"] = parsed.preferences
    if parsed.physical_exam:
        payload["physical_exam"] = parsed.physical_exam
    if not payload:
        return student_id, {}

    if student_id:
        row = repo.get_student(session, student_id)
        if row is None:
            return student_id, {}
        # 省份是档案的**根本属性**：改它意味着换一套投档规则、换一个一分一段表。
        # 因此已有档案时**不因一句话就覆盖**——万一解析错了（例如把校名里的"上海"当成考生省份），
        # 后果是整套推荐都错。要改省份请到建档向导。
        if row.province and payload.get("province") and payload["province"] != row.province:
            payload.pop("province")
        student_service.update(session, row, payload)
        return student_id, payload

    province = payload.get("province")
    if not province:
        # 建档需要省份；没有就等追问，不猜一个
        return None, {}
    created = student_service.create(
        session,
        {
            "province": province,
            "year": CURRENT_YEAR,
            "subjects": payload.get("subjects", []),
            "total_score": payload.get("total_score"),
            "rank": payload.get("rank"),
            "gender": payload.get("gender"),
            "foreign_language": payload.get("foreign_language", "英语"),
            "physical_exam": payload.get("physical_exam", {}),
            "preferences": payload.get("preferences", {}),
        },
    )
    return created.id, payload


# ---------------------------------------------------------------------------
# 确定性路径
# ---------------------------------------------------------------------------
def _run(ctx: ToolContext, records: list[ToolCallRecord], name: str, args: dict[str, Any]) -> ToolResult:
    """调用工具并留痕（留痕是护栏的判据，也是给考生看的"查了什么"）。"""
    result = call_tool(ctx, name, args)
    records.append(ToolCallRecord(name=name, arguments=result.arguments, result=result.to_payload()))
    return result


def _answer_about_school(
    ctx: ToolContext,
    records: list[ToolCallRecord],
    college_id: str | None,
    college_name: str | None,
    province: Any,
    *,
    fallback_message: str = "",
) -> str:
    """回答"某校的分数线/位次"这类问题；**查不到就明确说查不到**。

    三种情形必须区分开，否则就会变成编造：
    1. 校名看起来像但库里没有这所 → 说"库里没有"，绝不套用相似名字的数据；
    2. 库里有这所，但它在考生省份没有招生单位 → 说清是哪一种缺失；
    3. 有单位但没历史记录（新增专业）→ 说"无历史"，并提示不得当保底。
    """
    if not college_name:
        # 关键词命中但没提取到校名（例如问"XX大学"之外的说法）：用原话诚实回绝
        return narrator.narrate_no_data(
            (fallback_message or "").strip()[:20],
            "我没有在院校库里匹配到具体校名；说个完整校名我再查",
        )
    if college_id is None:
        return narrator.narrate_no_data(
            f"{college_name} 的投档数据",
            "本系统院校库里没有这所学校，所以它的分数线、位次我一个数字都给不出",
        )
    if not province:
        return "先告诉我你在哪个省参加高考，我才能查该校在你省的投档记录。"
    units = _run(
        ctx,
        records,
        "search_units",
        {"province": province, "year": CURRENT_YEAR, "keyword": college_name, "limit": 5},
    )
    matched = list(units.data.get("units") or [])
    if not matched:
        return narrator.narrate_no_data(
            f"{college_name} 在你省的招生计划",
            "库里没有该校在你省的投档单位记录，因此它的分数线我一个数字都给不出",
        )
    history = _run(ctx, records, "get_unit_history", {"unit_id": matched[0]["unit_id"], "years": 3})
    if not history.ok:
        return narrator.narrate_no_data(
            f"{college_name} 的历史", (history.error or {}).get("message", "")
        )
    return narrator.narrate_history(
        history.data, f"{college_name} · {matched[0].get('major_name', '')}"
    )


def _answer_about_school_level(
    ctx: ToolContext,
    records: list[ToolCallRecord],
    college_id: str | None,
    college_name: str | None,
) -> str:
    """回答"某校怎么样 / 算不算好学校"（ADR-019）。

    ★ 与 :func:`_answer_about_school` 的分工：那个答"多少分"（历史位次），
    这个答"什么层次"（判据 + level_score 的来源规则）。
    考生问"浙工大怎么样"却收到一串位次数字，就是答非所问（实测踩到）。

    ★ 红线：**只转述工具返回的判据**，不给排名、不下"好/差"结论、不编就业率。
    库里没有这所学校时诚实回绝（绝不套用相似名字）。
    """
    if not college_name:
        return narrator.narrate_no_data(
            "这所院校的层次",
            "我没有在院校库里匹配到具体校名；说个完整校名我再查",
        )
    if college_id is None:
        return narrator.narrate_no_data(
            f"{college_name} 的层次判据",
            "本系统院校库里没有这所学校，所以它的层次、标签我一个都给不出",
        )
    result = _run(ctx, records, "get_college_level_facts", {"college_id": college_id})
    if not result.ok:
        return narrator.narrate_no_data(
            f"{college_name} 的层次判据", (result.error or {}).get("message", "")
        )
    # 把证据链一起交给叙述器（工具返回值里的 source_url 要能透出到回答里）
    payload = dict(result.data)
    payload["_evidence"] = list(result.evidence or [])
    return narrator.narrate_college_level(payload)


def _deterministic_text(
    ctx: ToolContext,
    records: list[ToolCallRecord],
    intent: str,
    message: str,
    facts: dict[str, Any],
) -> str:
    parsed = parse_profile_fields(message)
    province = facts.get("province") or parsed.fields.get("province")

    # ---- 提到具体院校时，先答"这所学校"的问题 ----
    # 「澳门大学的录取位次是多少」里的"位次"会把意图判成 rank（= 换算我自己的位次），
    # 于是答非所问、还输出了一堆合规但不相干的数字（实测踩过）。
    # **校名比关键词更具体**，优先它。
    colleges = repo.load_colleges(ctx.session)
    catalog = {college.name: college.id for college in colleges.values()}
    school_id, school_token = find_school_mention(message, catalog)
    # 但如果考生在这句话里报了分数/位次，那是在补档案，不能拿校名把话岔开
    reports_own_data = bool(parsed.fields.get("total_score") or parsed.fields.get("rank"))

    # ★ ADR-019：先分流"这所学校怎么样（层次/实力）"与"这所学校多少分（历史）"。
    #   两者都必须先有校名；问层次时不能拿位次数字糊弄（考生问的是"算不算好学校"）。
    if school_token and not reports_own_data and intent == "college_level":
        return _answer_about_school_level(ctx, records, school_id, school_token)

    if school_token and not reports_own_data and intent in ("history", "rank", "unknown", "recommend"):
        return _answer_about_school(ctx, records, school_id, school_token, province)

    # 考生只是"报了情况"而没提问（"我是浙江的，选了物化生，考了 640"）：
    # 这不是 unknown，回执 + 还缺什么才是对的反应。
    if intent == "unknown" and (parsed.fields or parsed.subjects):
        result = _run(ctx, records, "list_missing_fields", {})
        missing = list(result.data.get("missing_fields") or [])
        return narrator.narrate_profile_update(facts, missing, questions=build_questions(missing))

    if intent == "greeting":
        result = _run(ctx, records, "list_missing_fields", {})
        missing = list(result.data.get("missing_fields") or [])
        if missing:
            return (
                "你好，我是志愿规划助手。\n"
                + narrator.narrate_missing(result.data)
                + "\n你也可以一次性告诉我：省份、3 门选考科目、总分（知道位次的话一并说）。"
            )
        return (
            "你好，你的档案是齐的。可以直接问我，比如：\n"
            "- 我这个位次大概能报什么？\n"
            "- 浙江最多能填几个志愿？\n"
            "- 查某个学校往年的投档情况（说出院校名即可）。"
        )

    if intent == "thanks":
        return "不客气。要提醒的是：志愿表上的顺序决定检索结果，最想去的必须放最前面。"

    if intent == "missing":
        result = _run(ctx, records, "list_missing_fields", {})
        missing = list(result.data.get("missing_fields") or [])
        text = narrator.narrate_missing(result.data)
        questions = build_questions(missing)
        if questions:
            text += "\n" + "\n".join(
                f"{index}. {question}" for index, question in enumerate(questions, 1)
            )
        return text

    if intent == "rule":
        if not province:
            return "你还没告诉我你在哪个省。省份决定投档模式和志愿数量，先说这个我才能答。"
        result = _run(ctx, records, "get_province_rule", {"province": province})
        if not result.ok:
            return narrator.narrate_no_data("该省投档规则", (result.error or {}).get("message", ""))
        return narrator.narrate_rule(result.data)

    if intent == "rank":
        score = parsed.fields.get("total_score") or facts.get("total_score")
        if not province:
            return "先告诉我你在哪个省参加高考，我才能用对的一分一段表换算位次。"
        if not score:
            return "告诉我你的高考总分，我用当年一分一段表给你换算位次（位次比分数可靠）。"
        result = _run(
            ctx,
            records,
            "get_rank_by_score",
            {"province": province, "year": CURRENT_YEAR, "score": int(score)},
        )
        if not result.ok:
            return narrator.narrate_no_data("位次换算", (result.error or {}).get("message", ""))
        return narrator.narrate_rank(result.data)

    if intent == "history":
        if not province:
            return "先告诉我你在哪个省参加高考，我才能查该校在你省的投档记录。"
        return _answer_about_school(ctx, records, None, None, province, fallback_message=message)

    if intent == "recommend":
        if facts.get("missing_fields"):
            result = _run(ctx, records, "list_missing_fields", {})
            return narrator.narrate_missing(result.data)
        result = _run(ctx, records, "recommend_units", {"limit": 12})
        if not result.ok:
            return narrator.narrate_no_data("推荐结果", (result.error or {}).get("message", ""))
        return narrator.narrate_recommendation(result.data)

    if intent == "risk":
        plan = None
        if facts.get("student_id"):
            plans = repo.list_plans(ctx.session, str(facts["student_id"]))
            plan = plans[-1] if plans else None
        if plan is not None:
            result = _run(ctx, records, "scan_risks", {"plan_id": plan.id})
            if result.ok:
                return narrator.narrate_risks(result.data)
        return (
            "风险这块最要紧的三条，你先记住：\n"
            "1. 院校专业组模式下**不服从调剂 = 主动接受退档风险**；\n"
            "2. 保底要真保底——不能只看概率高，还要看它近三年最难那年是不是也比你位次靠后一大截；\n"
            "3. 平行志愿检索严格按你填的顺序，最想去的必须放最前面。\n"
            "你还没有已保存的志愿表，等生成之后我可以逐条扫风险给你看。"
        )

    if intent == "concept":
        base = (
            "两条主线先分清：\n"
            "- 「专业(类)+院校」：一个志愿就是一个具体专业，**没有专业调剂概念**，报满即录；\n"
            "- 「院校专业组」：一个志愿是一个组，组内有多个专业，**必须选择是否服从调剂**，"
            "不服从就等于接受退档风险；而且冲进去也可能被调剂到组里你不想读的专业。\n"
            "还有一个通用原则：**位次比分数可靠**。每年题目难度和考生人数都在变，跨年比较一律用位次。"
        )
        if province:
            result = _run(ctx, records, "get_province_rule", {"province": province})
            if result.ok:
                base += "\n\n" + narrator.narrate_rule(result.data)
        return base

    return (
        narrator.narrate_no_data(message.strip()[:20])
        + "\n可以试试这些问法：\n"
        "- 直接说你的情况：省份 + 3 门选考科目 + 总分（知道位次就一并说）\n"
        "- 「浙江最多能填几个志愿、有没有专业调剂？」\n"
        "- 「查 XX大学的投档历史」\n"
        "- 「帮我推荐一些学校」"
    )


def _deterministic_reply(
    session: Session, student_id: str | None, message: str, facts: dict[str, Any]
) -> AgentReply:
    ctx = ToolContext(session=session, student_id=student_id)
    records: list[ToolCallRecord] = []
    intent = detect_intent(message)
    text = _deterministic_text(ctx, records, intent, message, facts)
    return _finalize(text, records, facts, mode="deterministic")


# ---------------------------------------------------------------------------
# LLM 路径（工具调用循环 + 护栏）
# ---------------------------------------------------------------------------
def _llm_reply(
    session: Session,
    client: LLMClient,
    student_id: str | None,
    message: str,
    facts: dict[str, Any],
) -> AgentReply:
    ctx = ToolContext(session=session, student_id=student_id)
    records: list[ToolCallRecord] = []
    settings = get_settings()
    history_rows = list(facts.get("_history") or [])
    context = {key: value for key, value in facts.items() if not key.startswith("_") and key != "session_id"}
    messages = prompts.build_messages(
        user_message=message, history=history_rows, context=context
    )

    final_text = ""
    for _ in range(max(1, settings.llm_max_tool_rounds)):
        response = client.complete(messages, TOOL_SCHEMAS)
        if not response.tool_calls:
            final_text = response.content
            break
        messages.append(
            {
                "role": "assistant",
                "content": response.content or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in response.tool_calls
                ],
            }
        )
        for call in response.tool_calls:
            result = call_tool(ctx, call.name, call.arguments)
            records.append(
                ToolCallRecord(name=call.name, arguments=result.arguments, result=result.to_payload())
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps(result.to_payload(), ensure_ascii=False),
                }
            )
    else:
        # 轮次用尽仍未收敛：不编内容，走确定性路径兜底
        return _deterministic_reply(session, student_id, message, facts)

    if not final_text.strip():
        return _deterministic_reply(session, student_id, message, facts)
    return _finalize(final_text, records, facts, mode="llm")


# ---------------------------------------------------------------------------
# 护栏 + 收口
# ---------------------------------------------------------------------------
def _finalize(
    text: str, records: list[ToolCallRecord], facts: dict[str, Any], *, mode: str
) -> AgentReply:
    guard: GuardResult = guard_response(text, records, known_facts=facts)
    warnings: list[str] = []
    if guard.rewritten:
        warnings.append(
            "护栏拦截了一次可能的编造（"
            + "、".join(guard.codes)
            + "）；已改写为安全回复，原始回复未发送给考生。"
        )
    return AgentReply(
        content=guard.reply,
        tool_calls=[
            {"name": record.name, "arguments": dict(record.arguments), "result": record.result}
            for record in records
        ],
        missing_fields=list(facts.get("missing_fields") or []),
        mode=mode,
        blocked=guard.rewritten,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def respond(
    session: Session,
    session_id: str,
    message: str,
    student_id: str | None = None,
) -> AgentReply:
    """处理一轮对话：解析 → 建档 → 取数 → 叙述 → 护栏 → 落库。"""
    repo.append_chat_message(
        session,
        message_id=_next_id(),
        session_id=session_id,
        role="user",
        content=message,
        student_id=student_id,
    )

    parsed = parse_profile_fields(message)
    student_id, applied = _apply_parsed_profile(session, student_id, parsed)
    facts = build_facts(session, student_id)
    facts["_history"] = [
        {"role": row.role, "content": row.content}
        for row in repo.list_chat_messages(session, session_id)[-HISTORY_WINDOW:]
        if row.role in ("user", "assistant")
    ]

    client: LLMClient | None = None
    try:
        client = get_llm_client()
    except LLMError:
        client = None

    if client is not None:
        try:
            reply = _llm_reply(session, client, student_id, message, dict(facts))
        except LLMError as exc:
            # 模型不可用不是编造的理由：退回确定性路径，并如实告知
            reply = _deterministic_reply(session, student_id, message, dict(facts))
            reply.mode = "deterministic-fallback"
            reply.warnings.append(f"LLM 不可用（{exc}），已改用规则路径回答。")
    else:
        reply = _deterministic_reply(session, student_id, message, dict(facts))

    reply.applied_fields = applied
    reply.student_id = student_id
    # 首次回复必须带免责声明（AGENTS.md §12）
    is_first = len(repo.list_chat_messages(session, session_id)) <= 1
    if is_first:
        reply.content = f"{DISCLAIMER}\n\n{reply.content}"

    repo.append_chat_message(
        session,
        message_id=_next_id(),
        session_id=session_id,
        role="assistant",
        content=reply.content,
        student_id=student_id,
        tool_calls=reply.tool_calls,
        missing_fields=reply.missing_fields,
        mode=reply.mode,
        blocked=reply.blocked,
    )
    return reply


def history(session: Session, session_id: str) -> list[dict]:
    return [repo.row_to_chat_message(row) for row in repo.list_chat_messages(session, session_id)]


def sse_frames(reply: AgentReply, session_id: str) -> Iterator[str]:
    """把**已经算完并过完护栏**的一轮结果切成 SSE 帧：``start`` → ``delta`` → ``done``。

    为什么不逐 token 流式调模型：agent 走一遍工具 + 护栏需要完整结果，
    逐 token 转发会让"要不要拦截"变成一件做不到的事——宁可让文字整体出现，
    也不能把未过护栏的内容吐给考生。
    """
    yield _frame("start", {"session_id": session_id, "disclaimer": DISCLAIMER})
    for chunk in _chunks(reply.content):
        yield _frame("delta", {"text": chunk})
    yield _frame(
        "done",
        {
            "content": reply.content,
            "missing_fields": reply.missing_fields,
            "tool_calls": reply.tool_calls,
            "mode": reply.mode,
            "blocked": reply.blocked,
            "warnings": reply.warnings,
            "applied_fields": reply.applied_fields,
            "student_id": reply.student_id,
        },
    )


def _chunks(text: str, size: int = 24) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


def _frame(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def reset(session: Session, session_id: str | None = None) -> int:
    """清空会话（测试与"清空对话"用）。``session_id=None`` 时清空全部。"""
    if session_id:
        return repo.delete_chat_session(session, session_id)
    rows = list(session.query(db.ChatMessage).all())
    for row in rows:
        session.delete(row)
    session.flush()
    return len(rows)


__all__ = [
    "DISCLAIMER",
    "HISTORY_WINDOW",
    "AgentReply",
    "build_facts",
    "history",
    "reset",
    "respond",
    "sse_frames",
]
