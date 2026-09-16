"""自然语言 → 结构化输入（AGENTS.md §3.3 第 1 件事、§9.2 追问策略）。

本模块有**两个职责**，都必须是确定性的（可单测、可复现）：

1. ``parse_profile_fields``：从考生原话里抽出档案字段（省份/选考/分数/位次/体检…）。
   **只抽明确说出来的**——缺字段就交给追问，绝不替考生假设（§9.2 禁止条款 3）。
2. ``detect_intent``：判断考生想干什么，供**无 LLM 时的确定性路径**使用。
   这条路径不是"降级玩具"：没有配置 LLM 时它就是 /chat 的全部能力，
   而它的每个数字都来自工具、每句话都过护栏。

为什么意图识别要写成规则而不是丢给模型
--------------------------------------
配置了 LLM 时由模型决定调用哪个工具；但（a）不能部署一个"没配 key 就完全不能用"的功能，
（b）幻觉测试需要一个**不受模型随机性影响**的对照组。规则式路由给出的答案天然零编造，
正好可以和 LLM 路径做交叉验证。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 词表
# ---------------------------------------------------------------------------
PROVINCE_ALIASES: dict[str, str] = {
    "浙江": "zhejiang",
    "浙": "zhejiang",
    "上海": "shanghai",
    "沪": "shanghai",
    "北京": "beijing",
    "京": "beijing",
    "山东": "shandong",
    "鲁": "shandong",
    "天津": "tianjin",
    "津": "tianjin",
    "海南": "hainan",
    "琼": "hainan",
}

#: 选考科目别名 → 招生计划字段口径（DOMAIN_RULES §2.4）。
#: ⚠️ 官方行文"生物/生物学"、"政治/思想政治"并存，别名必须都收，
#: 但**归一化后**统一用招生计划里的写法（否则硬匹配会漏）。
SUBJECT_ALIASES: dict[str, str] = {
    "物理": "物理",
    "化学": "化学",
    "生物": "生物",
    "生物学": "生物",
    "生命科学": "生物",
    "思想政治": "思想政治",
    "政治": "思想政治",
    "历史": "历史",
    "地理": "地理",
    "技术": "技术",
    "通用技术": "技术",
    "信息技术": "技术",
}

#: 意向专业（软偏好）。做法是"触发词 + 截到分隔符"，再剥掉尾巴上的"专业/类/方向"。
#:
#: 为什么不用"关键词表"去猜：考生说"我选了物理化学生物，想学计算机"时，
#: 关键词表会把**选考科目**物理/化学/生物也当成专业意向抓进来（实测过）。
#: 只认"想学/想读/意向…"这类显式触发词，虽然会漏，但不会把考生的选考科目误当成志愿意向。
_MAJOR_INTENT = re.compile(
    r"(?:想学|想读|意向(?:是|专业是)?|喜欢|倾向于|想报|打算报)\s*([^，,。；;、\s]{2,12})"
)
_MAJOR_SUFFIXES = ("专业", "大类", "类", "方向", "学科")


def _extract_major_intents(text: str) -> list[str]:
    intents: list[str] = []
    for match in _MAJOR_INTENT.finditer(text):
        value = match.group(1)
        for suffix in _MAJOR_SUFFIXES:
            if value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                break
        if value and value not in intents:
            intents.append(value)
    return intents

_TUITION_MAX = re.compile(r"(?:学费)?(?:不超过|最多|上限|以内|以下)\s*(\d{3,6})")
_SCORE = re.compile(r"(\d{3})\s*分|考了\s*(\d{3})|总分\s*(\d{3})")
_RANK = re.compile(r"(?:位次|排名|名次|省排)\D{0,4}(\d{1,3}(?:,\d{3})+|\d{3,7})")
_HEIGHT = re.compile(r"身高\s*(\d{3})")
_LANGUAGE = re.compile(r"(英语|日语|俄语|德语|法语|西班牙语)")

#: "看起来像校名"的片段（以 大学/学院/学校 结尾）。
_SCHOOL_LIKE = re.compile(r"[\u4e00-\u9fa5A-Za-z]{2,12}?(?:大学|学院|学校)")

#: 泛指的校名片段**不是**具体院校，不能被当成一次查询：
#: 「我这个位次能报什么学校」里的"什么学校"如果被当成校名，就会答成"库里没有这个院校"。
_GENERIC_SCHOOL_WORDS = (
    "什么",
    "哪些",
    "哪个",
    "哪所",
    "几所",
    "一所",
    "一些",
    "这个",
    "那个",
    "这所",
    "那所",
    "所有",
)

#: 校名前常见的动词/语气词，匹配到之后要剥掉，避免把"查一下澳门大学"整串当成校名
_LEADING_FILLER = re.compile(
    r"^(?:请|麻烦|帮我|帮忙|我想去|我想报|我想上|我想|我要|想|查一下|查查|查|看一下|看看|看|"
    r"了解下|了解|请问|问一下|关于|说一下|说说|告诉我|想知道)+"
)

_INTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("missing", re.compile(r"缺(什么|哪些)|还差|没填完|没填齐|补齐|完成了吗|档案.*(全|齐|完整)")),
    # `concept` / `risk` 必须排在 `rule` 之前：
    # 「什么是院校专业组」「服从调剂会不会被退档」都会被 `rule` 的宽关键词抢走（实测踩过）
    ("concept", re.compile(r"什么是|啥是|是什么意思|区别|科普|解释一下")),
    ("risk", re.compile(r"风险|退档|滑档|保底|兜底|会被调剂")),
    # 注意：`rule` 里**不放**裸"投档"——"查某校的投档历史"会被它抢走（实测踩过）
    (
        "rule",
        re.compile(
            r"能填几个|几个志愿|多少个志愿|志愿数|平行志愿|顺序志愿|服从调剂|调剂|专业组"
            r"|投档规则|投档模式|投档比例|批次|规则|怎么填"
        ),
    ),
    ("history", re.compile(r"分数线|录取线|投档线|历年|往年|历史|最低分|录取情况|多少分能上")),
    # `recommend` 必须排在 `rank` 之前：「我这个位次能报什么学校」是问推荐，
    # 只是句子里带了"位次"两个字（实测踩过：先判 rank 会答成"换算位次"）
    ("recommend", re.compile(r"推荐|能上|能报|报什么|什么学校|哪些学校|冲稳保|怎么选|志愿表|生成志愿")),
    ("rank", re.compile(r"位次|排名|换算|等效分|我考了|我的分")),
    ("greeting", re.compile(r"^\s*(?:你好|您好|在吗|hi|hello|hey)", re.IGNORECASE)),
    ("thanks", re.compile(r"谢谢|感谢|多谢|辛苦")),
)


# ---------------------------------------------------------------------------
# 结果结构
# ---------------------------------------------------------------------------
@dataclass
class ParsedProfile:
    """从原话里抽出的档案字段（**只包含明确说出的**）。"""

    fields: dict[str, Any] = field(default_factory=dict)
    subjects: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    physical_exam: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.fields or self.subjects or self.preferences or self.physical_exam)


#: 缺字段 → 追问话术（一次最多问 3 个，§9.2）。
_QUESTION_TEMPLATES: dict[str, str] = {
    "province": "你在哪个省参加高考？（浙江 / 上海 / 北京 / 山东 / 天津 / 海南）",
    "subjects": "你的 3 门选考科目是什么？（必须是恰好 3 门）",
    "total_score": "你的高考总分是多少？",
    "rank": "你知道自己的位次吗？知道就直接说（不知道的话，填了总分我可以帮你换算）。",
}


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def _find_province(text: str) -> str | None:
    for alias, code in PROVINCE_ALIASES.items():
        if alias in text:
            return code
    return None


def find_subjects(text: str) -> list[str]:
    """抽取提到的选考科目（去重、按招生计划口径归一化）。"""
    found: list[str] = []
    for alias, canonical in SUBJECT_ALIASES.items():
        if alias in text and canonical not in found:
            found.append(canonical)
    return found


def parse_profile_fields(text: str) -> ParsedProfile:
    """从原话里抽字段。**抽不到就是抽不到**，不猜、不补默认值。"""
    parsed = ParsedProfile()

    # ⚠️ 省份必须在**剥掉校名之后**再匹配：校名里天然带省份，
    # "上海大学的最低录取位次是多少" 会被当成"考生在上海"（实测踩过，
    # 后果很严重：一句话就把考生档案的省份改成了上海）。
    text_without_schools = _SCHOOL_LIKE.sub("", text)
    province = _find_province(text_without_schools)
    if province:
        parsed.fields["province"] = province

    parsed.subjects = find_subjects(text)

    score_match = _SCORE.search(text)
    if score_match:
        raw = next((group for group in score_match.groups() if group), None)
        if raw:
            parsed.fields["total_score"] = int(raw)

    rank_match = _RANK.search(text)
    if rank_match:
        parsed.fields["rank"] = int(rank_match.group(1).replace(",", ""))

    if re.search(r"男生|男孩|我是男|性别男", text):
        parsed.fields["gender"] = "男"
    elif re.search(r"女生|女孩|我是女|性别女", text):
        parsed.fields["gender"] = "女"

    language = _LANGUAGE.search(text)
    if language:
        parsed.fields["foreign_language"] = language.group(1)

    if "色盲" in text:
        parsed.physical_exam["color_blindness"] = True
    if "色弱" in text:
        parsed.physical_exam["color_weakness"] = True
    height = _HEIGHT.search(text)
    if height:
        parsed.physical_exam["height_cm"] = int(height.group(1))

    intents = _extract_major_intents(text)
    if intents:
        parsed.preferences["intended_major_categories"] = intents

    tuition = _TUITION_MAX.search(text)
    if tuition:
        parsed.preferences["budget_max"] = int(tuition.group(1))

    return parsed


def build_questions(missing: Sequence[str], limit: int = 3) -> list[str]:
    """把缺失字段变成追问（§9.2：一次最多问 3 个）。"""
    return [_QUESTION_TEMPLATES[field] for field in missing[:limit] if field in _QUESTION_TEMPLATES]


def detect_intent(text: str) -> str:
    """意图识别（确定性）。未知意图返回 ``"unknown"``。"""
    stripped = text.strip()
    if not stripped:
        return "unknown"
    for intent, pattern in _INTENT_RULES:
        if pattern.search(stripped):
            return intent
    return "unknown"


def find_named_entity(text: str, names: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    """在文本里找**库里真实存在**的院校/专业名（返回 ``(id, name)``）。

    这是确定性路径能回答"XX大学去年多少分"的关键：名字必须在库里匹配上，
    否则就诚实地说"库里没有这个院校"——绝不用一个相似的名字顶替。
    取**最长匹配**，避免"北京大学"被"大学"这类短名先命中。
    """
    best: tuple[str, str] | None = None
    for entity_id, name in names:
        if not name or name not in text:
            continue
        if best is None or len(name) > len(best[1]):
            best = (entity_id, name)
    return best


def find_school_mention(
    text: str, catalog: Mapping[str, str]
) -> tuple[str | None, str | None]:
    """找文本里提到的院校。

    返回 ``(catalog_id, token)``：

    - ``catalog_id`` 不为 None → 库里真有这所，带着 id 去查它的投档历史；
    - ``catalog_id`` 为 None 但 ``token`` 不为 None → **看起来像校名但库里没有**
      （如"澳门大学""华夏科技大学"）→ 上层必须回答"没有这所的数据"，
      **绝不能因为名字像就套用别的学校的数据**。
    """
    for match in _SCHOOL_LIKE.finditer(text):
        token = _LEADING_FILLER.sub("", match.group(0))
        if not token or any(word in token for word in _GENERIC_SCHOOL_WORDS):
            continue
        return catalog.get(token), token
    return None, None


__all__ = [
    "PROVINCE_ALIASES",
    "SUBJECT_ALIASES",
    "ParsedProfile",
    "build_questions",
    "detect_intent",
    "find_named_entity",
    "find_school_mention",
    "find_subjects",
    "parse_profile_fields",
]
