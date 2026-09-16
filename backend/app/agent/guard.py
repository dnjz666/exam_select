"""幻觉护栏（AGENTS.md §9.3）—— 全项目"宁可不答，不可编造"的最后一道闸门。

为什么不能只靠 System Prompt
---------------------------
提示词是"请求"不是"保证"：模型仍可能一本正经地编出一个分数线。所以护栏必须在**模型之外**
做后置校验，而且判据必须是**确定性的**：

1. 正则提取回复中的"数据型数字断言"（分数 / 位次 / 百分比 / 计划数 / 志愿数）；
2. 与**本次会话所有工具返回值**里的数字比对（Pydantic 结构里的 int/float，
   外加调用方显式给定的"已知事实"，如考生自己的分数）；
3. 任何一个对不上 → **整条回复拦截**，重写为"我需要先查一下数据"；
4. 命中绝对化词表（保证录取 / 一定能上 / 百分百…）→ 同样拦截。

三条容易被做错的设计点（都有测试守着）
--------------------------------------
- **只从结构的数值字段收集白名单，不从字符串里抓数字**：``source_url`` 里的年份、
  ``unit_id`` 里的专业代码都是数字，若把它们当作"允许出现的数字"，护栏就被开了后门
  （编造的 2026 分正好撞上 URL 里的 2026）。
- **绝不过度拦截**："一定要留足保底"是正当建议，不是绝对化承诺；"浙江 3+3 / 7 选 3"
  是模式名称，不是数据。护栏宁可漏掉边缘表述，也不能把合规回答全毙掉——
  一个总在误拦的护栏，最后一定会被人关掉。
- **百分比与概率同尺度比对**：工具返回 ``0.62``，回复说 "62%" 是同一件事，
  必须能对上；否则每一次合规引用都会被拦。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 数值断言的分类与匹配容差
# ---------------------------------------------------------------------------
#: 展示四舍五入容差。工具给 659.6，回复写 "660 分" 是合规的；
#: 但 12340 与 12300 之间隔着 40 个位次，不能被容差吞掉。
ROUNDING_TOLERANCE = 0.5
#: 百分比容差按"百分点"计（0.005 = 0.5pp）：工具 0.615 → 回复 "62%" 合规
PERCENT_TOLERANCE = 0.005

#: 数字字面量（含千分位；先长后短，避免 "12,340" 被切成 "12" 和 "340"）
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

#: 上下文关键词 → 断言类别（按优先级排列，先匹配到的胜出）
_CONTEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rank", re.compile(r"位次|名次|排名|位序")),
    ("score", re.compile(r"分数|投档线|录取线|最低分|平均分|等效分|总分|考了")),
    ("plan_count", re.compile(r"计划|招生|招收|名额")),
    ("volunteer_cap", re.compile(r"志愿|专业组")),
)

#: 行首的"1. / 2、/ 3)"是**列表序号**，不是数据断言。
#: 不排除它就会出现这种误拦：追问文案"…位次。\n1. 你的 3 门选考科目…"里的"1"
#: 会因为 6 字内有"位次"而被当成位次断言，整条合规回复被拦掉（实测踩过）。
_LIST_MARKER = re.compile(r"^\s*\d{1,2}\s*[.、)）]")

#: 关键词与数字的最大距离（字符）。**这个窗口必须窄**：
#: 用 ±12 时，"3 门选考科目、总分" 里的 "3" 会因为 12 字内有"总分"而被判成分数断言，
#: 结果一句完全合规的追问被整条拦掉（实测踩过）。窄窗口 + 下面的数值下限共同保证
#: "宁可漏掉边缘表述，也不误伤合规回答"。
_CONTEXT_WINDOW = 6

#: 各类断言的最小可信数值。低于下限的不是"数据断言"，而是"3 门""1 个"这类量词。
_MIN_VALUE: dict[str, float] = {
    "score": 100.0,  # 高考总分/投档线不可能低于 100
    "rank": 1.0,
    "plan_count": 1.0,
    "volunteer_cap": 2.0,
}

#: 绝对化表述：志愿填报里最危险的一类话术（§0 明令禁止）。
#: 每一条都写成"短语"而不是单个词——「一定」单独出现时多为正常建议
#:（"一定要留足保底"），只有与录取结果绑定才是承诺。
_ABSOLUTE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("BAO_ZHENG_LUQU", re.compile(r"保证(?:你)?(?:能)?(?:被)?(?:录取|投档|上大学|上)")),
    ("KEN_DING_NENG_SHANG", re.compile(r"(?:一定|肯定|绝对|必定|铁定|百分百|100%)\s*(?:能|可以|会)?\s*(?:被)?(?:录取|投档|上|进)")),
    ("WEN_SHANG", re.compile(r"稳上|稳了|保过|包过|必录|包录取|绝对不会退档")),
    ("BAI_FEN_BAI", re.compile(r"百分百|100\s*%")),
)


@dataclass(frozen=True)
class NumericAssertion:
    """回复里的一处数据型数字断言。"""

    kind: str  # rank | score | percent | plan_count | volunteer_cap
    raw: str
    value: float
    start: int
    end: int

    @property
    def display(self) -> str:
        return self.raw


@dataclass(frozen=True)
class ToolCallRecord:
    """一次工具调用（护栏据此判断"这个数字是不是查出来的"）。"""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None


@dataclass(frozen=True)
class GuardViolation:
    code: str  # UNSUPPORTED_NUMBER | ABSOLUTE_CLAIM
    detail: str
    raw: str


@dataclass(frozen=True)
class GuardResult:
    """护栏结论。``reply`` 永远是**可以发给考生**的文本。"""

    allowed: bool
    reply: str
    violations: tuple[GuardViolation, ...] = ()

    @property
    def rewritten(self) -> bool:
        return not self.allowed

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(violation.code for violation in self.violations)


#: 拦截后的兜底文案（§9.3：重写为"我需要查一下数据"）。
SAFE_FALLBACK = (
    "这个问题我需要先查到真实数据才能回答——我不能凭印象给你报分数线、位次或录取概率。\n"
    "请先在建档向导补齐档案，或在「推荐列表」页查看每个单位的官方来源证据；"
    "已有的数字我都会连同出处一起给你。\n"
    "宁可不答，不可编造。"
)


# ---------------------------------------------------------------------------
# 数字白名单的收集
# ---------------------------------------------------------------------------
def collect_numbers(payload: Any) -> set[float]:
    """递归收集结构里的 **int/float 数值字段**，作为"允许出现的数字"集合。

    ⚠️ 刻意**不解析字符串**：``source_url``（含年份）、``unit_id``（含专业代码）里的数字
    若进入白名单，护栏就有了后门——编造出来的数字可能刚好与 URL 里的某段数字相同。
    数值必须在结构里以数字类型出现，才算"工具确实返回过"。
    """
    found: set[float] = set()
    stack: list[Any] = [payload]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if isinstance(node, bool) or node is None:
            continue
        if isinstance(node, (int, float)):
            found.add(float(node))
            continue
        if isinstance(node, str):
            # 只接受"纯数字字符串"（如 JSON 往返后可能出现的数值），
            # 不做子串抽取——见上方后门说明。
            text = node.strip().replace(",", "")
            if text and re.fullmatch(r"-?\d+(?:\.\d+)?", text):
                found.add(float(text))
            continue
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, Mapping):
            stack.extend(node.values())
        elif isinstance(node, (list, tuple, set, frozenset)):
            stack.extend(node)
        elif hasattr(node, "model_dump"):  # Pydantic 模型
            stack.append(node.model_dump(mode="json"))
    return found


def collect_from_tool_calls(tool_calls: Sequence[ToolCallRecord]) -> set[float]:
    """把若干次工具调用的返回值合并成白名单。"""
    allowed: set[float] = set()
    for record in tool_calls:
        allowed |= collect_numbers(record.result)
    return allowed


# ---------------------------------------------------------------------------
# 断言提取
# ---------------------------------------------------------------------------
def _classify(text: str, start: int, end: int, raw: str) -> str | None:
    """判断这处数字属于哪类数据断言（None = 不是数据断言，放行）。

    两个判定技巧，都是被实测缺漏逼出来的：

    - **紧跟"分"就是分数**：``录取分是 638 分``、``最低分 660`` —— 中文里"分"紧跟数字
      是最强的分数信号。只靠关键词表会漏掉"录取分"（它既不是"最低分"也不是"分数"），
      而"录取分"恰恰是最常见的说法。
    - **按最近的关键词归类，而不是"窗口里出现过就算"**：在
      ``最低分 660，最低位次 12,340`` 里，660 的 ±6 字窗口同时含"最低分"与"最低位次"，
      谁先匹配谁赢的写法会把 660 判成位次（实测踩过）。距离最近者胜；
      距离相同时按 ``_CONTEXT_RULES`` 的声明顺序决胜。
    """
    # 1) 紧跟 % 的一定是百分比；紧跟"分"的一定是分数
    following = text[end : end + 2]
    if following.lstrip().startswith("%"):
        return "percent"
    if following.lstrip().startswith("分"):
        value = float(raw.replace(",", ""))
        return "score" if value >= _MIN_VALUE["score"] else None

    # 2) 行首列表序号（"1. 你的…"）不是数据断言
    line_start = text.rfind("\n", 0, start) + 1
    if _LIST_MARKER.match(text[line_start:end]):
        return None

    value = float(raw.replace(",", ""))
    window_start = max(0, start - _CONTEXT_WINDOW)
    window_end = min(len(text), end + _CONTEXT_WINDOW)
    context = text[window_start:window_end]

    # 2) 年份不是数据断言（"2026 年最低分 660" 里的 2026）
    if 1900 <= value <= 2100 and re.search(r"年", context):
        return None

    # 3) 就近归类，并过滤掉量词级的小数字
    best: tuple[tuple[int, int], str] | None = None
    for priority, (kind, pattern) in enumerate(_CONTEXT_RULES):
        if value < _MIN_VALUE.get(kind, 0.0):
            continue
        for match in pattern.finditer(text, window_start, window_end):
            distance = min(abs(match.start() - end), abs(start - match.end()))
            key = (distance, priority)
            if best is None or key < best[0]:
                best = (key, kind)
    return best[1] if best is not None else None


def extract_assertions(reply: str) -> list[NumericAssertion]:
    """提取回复中的全部数据型数字断言（说明性数字不在此列）。"""
    assertions: list[NumericAssertion] = []
    for match in _NUMBER.finditer(reply):
        raw = match.group(0)
        kind = _classify(reply, match.start(), match.end(), raw)
        if kind is None:
            continue
        value = float(raw.replace(",", ""))
        if kind == "percent" and abs(value - 100.0) < 1e-9:
            # "100%" 不作为数字断言（它由绝对化词表负责拦截），否则正常语境的
            # "覆盖率 100%" 会被误伤
            continue
        assertions.append(
            NumericAssertion(kind=kind, raw=raw, value=value, start=match.start(), end=match.end())
        )
    return assertions


def _supported(value: float, kind: str, allowed: Iterable[float]) -> bool:
    """这个数字是否能在"允许集合"里找到出处（含展示四舍五入容差）。"""
    target = value / 100.0 if kind == "percent" else value
    tolerance = PERCENT_TOLERANCE if kind == "percent" else ROUNDING_TOLERANCE
    for candidate in allowed:
        if abs(candidate - target) <= tolerance:
            return True
    return False


def find_absolute_claims(reply: str) -> list[GuardViolation]:
    """绝对化表述（"保证录取""一定能上"…）。"""
    violations: list[GuardViolation] = []
    for code, pattern in _ABSOLUTE_PATTERNS:
        for match in pattern.finditer(reply):
            violations.append(
                GuardViolation(code="ABSOLUTE_CLAIM", detail=f"{code}: {match.group(0)}", raw=match.group(0))
            )
    return violations


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def guard_response(
    reply: str,
    tool_calls: Sequence[ToolCallRecord] = (),
    *,
    known_facts: Mapping[str, Any] | None = None,
) -> GuardResult:
    """校验并（必要时）重写 LLM / 叙述器产出的回复。

    :param reply: 待校验文本
    :param tool_calls: **本次会话**内所有工具调用（不只本轮——考生会引用上文查过的数字）
    :param known_facts: 额外的已知事实（如考生自己的分数/位次）。这些是用户提供或系统
        已确认的数据，不是模型编造的，因此允许出现。
    """
    if not reply or not reply.strip():
        return GuardResult(allowed=True, reply=reply)

    allowed = collect_from_tool_calls(tool_calls)
    if known_facts:
        allowed |= collect_numbers(known_facts)

    violations: list[GuardViolation] = []

    for assertion in extract_assertions(reply):
        if not _supported(assertion.value, assertion.kind, allowed):
            violations.append(
                GuardViolation(
                    code="UNSUPPORTED_NUMBER",
                    detail=(
                        f"{assertion.kind} 断言 {assertion.raw} 在本次会话的工具返回值里找不到出处"
                        "（工具没查过，就不能说）"
                    ),
                    raw=assertion.raw,
                )
            )

    violations.extend(find_absolute_claims(reply))

    if not violations:
        return GuardResult(allowed=True, reply=reply)
    return GuardResult(allowed=False, reply=SAFE_FALLBACK, violations=tuple(violations))


__all__ = [
    "PERCENT_TOLERANCE",
    "ROUNDING_TOLERANCE",
    "SAFE_FALLBACK",
    "GuardResult",
    "GuardViolation",
    "NumericAssertion",
    "ToolCallRecord",
    "collect_from_tool_calls",
    "collect_numbers",
    "extract_assertions",
    "find_absolute_claims",
    "guard_response",
]
