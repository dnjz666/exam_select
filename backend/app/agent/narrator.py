"""工具返回值 → 名师口吻解释（AGENTS.md §3.3 第 2 件事、§9.2）。

铁律：**数字必须原样引用工具返回值**。
因此本模块的每个函数都只从工具 payload 里取数，绝不自己算、也绝不补默认值——
这也是护栏能放行的前提（护栏会把"工具没返回过的数字"整条拦掉）。

文风要求（§9.2）：直接、给依据、敢说不确定。宁可说"这个给不出余量，不能当保底"，
也不说"这个稳了"——后者是 §0 明令禁止的绝对化表述。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

MISSING_FIELD_LABELS: dict[str, str] = {
    "province": "省份",
    "subjects": "选考科目（恰好 3 门）",
    "total_score": "高考总分",
    "rank": "位次",
}

#: 省份代码 → 中文名（**仅用于显示**）。
#: 之所以在后端也留一份：叙述层需要说人话，而 `/meta/provinces` 只回代码。
#: 键集合由 tests/test_agent_*.py 断言与 `core.rules.PROVINCES` 一致，防止两边漂移。
PROVINCE_NAMES: dict[str, str] = {
    "zhejiang": "浙江",
    "shanghai": "上海",
    "beijing": "北京",
    "shandong": "山东",
    "tianjin": "天津",
    "hainan": "海南",
}


def province_name(code: Any) -> str:
    return PROVINCE_NAMES.get(str(code), str(code))

_TIER_NAMES: dict[str, str] = {
    "CHONG": "冲",
    "WEN": "稳",
    "BAO": "保",
    "DIAN": "垫",
    "TOO_RISKY": "基本无望",
    "NO_DATA": "无可用数据",
}

_CONFIDENCE_HINTS: dict[str, str] = {
    "HIGH": "数据完整、置信度高",
    "MEDIUM": "数据略有缺口、置信度中等",
    "LOW": "数据不足，参考价值有限",
    "NO_DATA": "无可用历史数据",
}


# ---------------------------------------------------------------------------
# 格式化（统一在这里做，保证"同一个数字到处写法一致"）
# ---------------------------------------------------------------------------
def _rank(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{round(value):,}"


def _score(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{round(value)}"


def _interval(interval: Any) -> str:
    if not isinstance(interval, Sequence) or isinstance(interval, str) or len(interval) < 2:
        return "—"
    low, high = float(interval[0]), float(interval[1])
    for digits in (0, 1, 2):
        left, right = f"{low * 100:.{digits}f}", f"{high * 100:.{digits}f}"
        if left != right:
            return f"{left}%–{right}%"
    return f"{low * 100:.2f}%–{high * 100:.2f}%"


def _money(value: Any) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "未收录（请核对招生章程）"
    return f"{round(value):,} 元/年"


def _plan(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{round(value):,} 人"


def _source_of(evidence: Sequence[Mapping[str, Any]] | None) -> str:
    """从证据链里取第一个可点开的来源（引用数字时必须能给出处）。"""
    for entry in evidence or ():
        url = entry.get("source_url")
        if isinstance(url, str) and url:
            return url
    return ""


# ---------------------------------------------------------------------------
# 各意图的叙述
# ---------------------------------------------------------------------------
def narrate_missing(data: Mapping[str, Any]) -> str:
    missing = list(data.get("missing_fields") or [])
    if not missing:
        return "你的档案已经齐全了，可以进入推荐列表看结果。"
    labels = "、".join(MISSING_FIELD_LABELS.get(field, field) for field in missing)
    return (
        f"你的档案还缺这几项：{labels}。\n"
        "信息不全我不会替你假设——比如「假设你是物理类」这种，猜错一次就可能把志愿表带偏。\n"
        "补齐后我再基于真实数据给你算。"
    )


def narrate_rule(data: Mapping[str, Any]) -> str:
    batch = data.get("main_batch") or {}
    if not batch:
        return "这个省的批次规则我这边没有数据，不能凭印象说。"
    mode = "专业(类)+院校" if batch.get("unit_type") == "MAJOR_COLLEGE" else "院校专业组"
    parallel = batch.get("is_parallel", True)
    lines = [
        f"{batch.get('batch_name', '该批次')}：投档单位是**{mode}**，"
        f"最多填 {_plan_cap(batch.get('max_volunteers'))} 个志愿"
        + (f"，每个专业组内 {batch['majors_per_group']} 个专业" if batch.get("majors_per_group") else "")
        + "。",
        f"这个批次是{'平行志愿' if parallel else '顺序志愿'}——"
        + (
            "检索严格按你填的顺序，所以最想去的必须放最前面。"
            if parallel
            else "第一志愿权重极高，第 2 志愿起只有第一志愿没招满才可能轮到，保底不能放在这里。"
        ),
    ]
    if batch.get("has_major_adjustment"):
        lines.append("有「服从专业调剂」选项：不服从调剂等于主动接受退档风险，务必逐条确认。")
    else:
        lines.append("这个模式没有专业调剂概念，报满即录——但也意味着冲的时候要更谨慎。")
    if batch.get("source_quote"):
        lines.append(f"官方原文：「{batch['source_quote']}」")
    if data.get("requires_banner"):
        lines.append("⚠️ 该省全部批次均未达官方原文等级，**其推荐结果不得用于真实填报**。")
    return "\n".join(lines)


def _plan_cap(value: Any) -> str:
    return f"{round(value)}" if isinstance(value, (int, float)) else "—"


def narrate_rank(data: Mapping[str, Any]) -> str:
    return (
        f"按 {data.get('year')} 年 {data.get('province')} 的一分一段表："
        f"{_score(data.get('score'))} 分对应位次 **{_rank(data.get('rank'))}**"
        f"（全省考生 {_rank(data.get('total_candidates'))} 人，百分位 {_percent(data.get('percentile'))}）。\n"
        "跨年比较请一律用位次，不要用分数——每年题目难度和考生人数都不一样。"
    )


def _percent(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value * 100:.2f}%"


def narrate_history(data: Mapping[str, Any], entity_name: str) -> str:
    records = list(data.get("records") or [])
    if not records:
        return f"{entity_name} 没有可用的往年记录，我不会凭印象给它编一个分数线。"
    lines = [f"{entity_name} 近几年的投档情况（按年份由近及远）："]
    for record in records:
        flags: list[str] = []
        if record.get("data_quality") == "DERIVED":
            flags.append("位次由分数反查")
        if record.get("is_collected"):
            flags.append("征集志愿（线偏低）")
        suffix = f"（{'、'.join(flags)}）" if flags else ""
        lines.append(
            f"- {record.get('year')} 年：最低分 {_score(record.get('min_score'))}，"
            f"最低位次 {_rank(record.get('min_rank'))}，计划 {_plan(record.get('plan_count'))}{suffix}"
        )
    source = _source_of(
        [{"source_url": record.get("source_url")} for record in records]
    )
    if source:
        lines.append(f"来源：{source}")
    lines.append("单年数据不能下结论：某一年异常低分，次年大概率反弹（大小年），要看趋势。")
    if len(records) < 3:
        lines.append(f"目前只有 {len(records)} 年记录，参考价值有限，置信度要打折。")
    return "\n".join(lines)


def narrate_college_level(data: Mapping[str, Any]) -> str:
    """院校层次判别的**专家口吻解读**（ADR-019）。

    ★ 红线：本函数**只转述工具返回值**，不新增任何数字、不给排名、不下"好/差"结论。
    它的价值在于把 `level_basis`（命中了哪条规则）与 `caveats`（诚实缺口）讲清楚，
    并说明"985/211/双一流不是唯一标准"这件事——这正是考生最需要被纠正的认知。
    """
    name = str(data.get("name") or "该院校")
    tags = list(data.get("level_tags") or [])
    affiliation = data.get("affiliation")
    is_public = data.get("is_public")
    score = data.get("level_score")
    basis = str(data.get("level_basis") or "")
    strength = data.get("region_strength")
    top_count = data.get("region_top_college_count")
    is_home = bool(data.get("is_home_province"))
    province = data.get("province")
    city = data.get("city")

    lines: list[str] = [
        f"{name}（{province_name(province)}·{city or '—'}）的层次判据："
    ]
    lines.append(f"- 层次标签：{'、'.join(tags) if tags else '无（没有 985/211/双一流 标签）'}")
    lines.append(f"- 隶属/属性：{affiliation or '未收录'}")
    lines.append(f"- 办学性质：{'公办' if is_public else '民办 / 独立学院'}")
    if isinstance(score, (int, float)):
        lines.append(f"- 层次得分：{score:.2f}（判据：{basis}）")
    else:
        lines.append(f"- 层次得分：数据缺失（判据：{basis}）")

    # 地区维度：只讲"地区资源"，不讲"这所学校排第几"
    # ★ 分母取自工具返回值，**不在叙述器里硬编码**（否则就是叙述器私自引入领域常量）
    if isinstance(strength, (int, float)) and top_count is not None:
        max_count = data.get("region_top_college_count_max")
        denominator = f" / {max_count}" if isinstance(max_count, int) else ""
        lines.append(
            f"- 所在省高教资源密度：{strength:.2f}"
            f"（该省双一流及以上院校 {top_count} 所{denominator}，"
            "用于地区比较，**不是**该校排名）"
        )
    if is_home:
        lines.append("- 这是你本省的院校：省内认可度、实习与就业半径通常更有优势。")

    for caveat in data.get("caveats") or []:
        lines.append(f"⚠️ {caveat}")

    note = data.get("note")
    if note:
        lines.append(str(note))
    lines.append(
        "要判断「能不能上」，得看它在**你省**的投档位次——说出你的省份和位次，我查历史记录。"
    )
    source = _source_of(data.get("_evidence"))
    if source:
        lines.append(f"来源：{source}")
    return "\n".join(lines)


def narrate_probability(data: Mapping[str, Any], entity_name: str) -> str:
    if data.get("probability") is None:
        return (
            f"{entity_name} 我算不出概率：没有可用的往年位次，也凑不出足够的同类单位做类比。\n"
            "按规矩这种情况就不给数字——宁可说不知道，也不给你一个假的百分比。"
        )
    tier = _TIER_NAMES.get(str(data.get("tier")), str(data.get("tier")))
    confidence = _CONFIDENCE_HINTS.get(str(data.get("confidence")), "")
    lines = [
        f"{entity_name}：估算录取概率 **{_interval(data.get('probability_interval'))}**（±1σ 区间），"
        f"属于「{tier}」档，{confidence}。",
        f"模型预测今年最低位次约 {_rank(data.get('predicted_min_rank'))}"
        + (f"，你的位次是 {_rank(data.get('student_rank'))}。" if data.get("student_rank") else "。"),
    ]
    reasons = [str(reason) for reason in (data.get("reasons") or [])]
    if reasons:
        lines.append("依据：" + "；".join(reasons[:3]))
    warnings = [str(warning) for warning in (data.get("warnings") or [])]
    if warnings:
        lines.append("注意：" + "；".join(warnings))
    source = _source_of(list(data.get("evidence") or []))
    if source:
        lines.append(f"来源：{source}")
    lines.append("概率是区间不是承诺：这一档能不能上，还要看当年报考热度和计划变化。")
    return "\n".join(lines)


def narrate_recommendation(data: Mapping[str, Any], *, limit_per_tier: int = 3) -> str:
    items = list(data.get("items") or [])
    stats = data.get("stats") or {}
    if not items:
        return (
            "按你的条件没有筛出可推荐的单位。"
            "可能是筛选条件太窄，或者选考科目组合把大部分专业挡在外面了——"
            "你可以放宽地区/学费限制再试。"
        )
    lines = ["按位次法给你排的结果（每项都带来源证据）："]
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("tier")), []).append(item)
    for tier in ("CHONG", "WEN", "BAO", "DIAN", "TOO_RISKY"):
        bucket = grouped.get(tier) or []
        if not bucket:
            continue
        lines.append(f"\n【{_TIER_NAMES.get(tier, tier)}】{len(bucket)} 个")
        for item in bucket[:limit_per_tier]:
            college = (item.get("college") or {}).get("name") or item.get("unit", {}).get("college_id")
            major = (item.get("major") or {}).get("name") or item.get("unit", {}).get("major_name")
            unit = item.get("unit") or {}
            lines.append(
                f"- {college} · {major}：{_interval(item.get('probability_interval'))}，"
                f"计划 {_plan(unit.get('plan_count'))}，学费 {_money(unit.get('tuition'))}"
            )
        if len(bucket) > limit_per_tier:
            lines.append(f"  （另有 {len(bucket) - limit_per_tier} 个同类，见推荐列表页）")
    filtered = stats.get("hard_filtered_out")
    if isinstance(filtered, int) and filtered:
        lines.append(f"\n另有 {filtered} 个单位被硬约束剔除（选考科目/体检/语种/学费上限等），不参与推荐。")
    lines.append(
        "\n提醒：上面只是候选，真要填志愿还要看专业组里有没有你不能接受的专业、"
        "以及垫底志愿够不够硬。"
    )
    return "\n".join(lines)


def narrate_risks(data: Mapping[str, Any]) -> str:
    risks = list(data.get("risks") or [])
    if not risks:
        return "这次扫描没有命中已知风险规则。**这不等于稳了**——规则没覆盖到的问题仍需你自己核对招生章程。"
    lines = [f"扫出 {len(risks)} 条风险，按严重程度看："]
    for risk in risks[:8]:
        level = {"HIGH": "高", "MEDIUM": "中", "LOW": "提示"}.get(str(risk.get("level")), "")
        lines.append(f"- [{level}] {risk.get('message')}\n  建议：{risk.get('suggestion')}")
    if len(risks) > 8:
        lines.append(f"（另有 {len(risks) - 8} 条，见志愿表页的风险面板）")
    return "\n".join(lines)


def narrate_plan_preview(data: Mapping[str, Any]) -> str:
    items = list(data.get("items") or [])
    if not items:
        return "按你的条件没排出志愿表：可能候选用尽，或被硬约束筛掉了。放宽条件再试。"
    distribution = data.get("tier_distribution") or {}
    parts = [f"{_TIER_NAMES.get(tier, tier)} {count}" for tier, count in distribution.items() if count]
    lines = [
        f"按你的条件排了一版**预览**（{data.get('batch_name')}，共 {len(items)} 个志愿）："
        + "、".join(parts) + "。",
        "排在前面的就是检索时优先级最高的；最后一档一定落在保/垫上，这是结构约束。",
    ]
    last = items[-1]
    lines.append(
        f"最后一个志愿是 {last.get('major_name')}（{_TIER_NAMES.get(str(last.get('tier')), last.get('tier'))}），"
        "它是你的兜底。"
    )
    violations = list(data.get("violations") or [])
    if violations:
        lines.append(f"有 {len(violations)} 项规则校验没通过，需要先处理。")
    lines.append("这只是预览，**没有保存**。确认后在「志愿表」页由你本人点击生成。")
    return "\n".join(lines)


def narrate_no_data(subject: str, reason: str = "") -> str:
    """数据缺失时的诚实回答（宁可说不知道）。"""
    tail = f"（{reason}）" if reason else ""
    return (
        f"关于「{subject}」我没有可用的数据{tail}。\n"
        "我不会凭印象给你报分数线、位次或录取率——志愿填报里一个编造的数字就可能让人滑档。\n"
        "你可以换个说法，或者告诉我具体的院校名，我去库里查。"
    )


def narrate_profile_update(
    facts: Mapping[str, Any], missing: Sequence[str], *, questions: Sequence[str] = ()
) -> str:
    """"我刚说了自己的情况"→ 回执 + 还缺什么 + 下一步。

    这里回显的数字（分数/位次）来自**系统档案**（``facts``），不是模型编的，
    所以护栏会放行——这正是 known_facts 存在的意义。
    """
    lines: list[str] = []
    recorded: list[str] = []
    if facts.get("province"):
        recorded.append(f"省份 {province_name(facts['province'])}")
    if facts.get("subjects"):
        recorded.append("选考 " + "、".join(str(item) for item in facts["subjects"]))
    if facts.get("total_score"):
        recorded.append(f"总分 {_score(facts['total_score'])}")
    if facts.get("rank"):
        recorded.append(f"位次 {_rank(facts['rank'])}")
    if recorded:
        lines.append("已记下你的信息：" + "；".join(recorded) + "。")

    if missing:
        labels = "、".join(MISSING_FIELD_LABELS.get(field, field) for field in missing)
        lines.append(f"还差：{labels}。")
        if questions:
            lines.extend(f"{index}. {question}" for index, question in enumerate(questions, 1))
        lines.append("补齐后我就能按你的位次给出可解释的推荐。")
    else:
        lines.append("档案齐了。要我按你的位次和选考科目推荐一版吗？也可以直接问某个学校的投档历史。")
    return "\n".join(lines)


__all__ = [
    "MISSING_FIELD_LABELS",
    "PROVINCE_NAMES",
    "province_name",
    "narrate_college_level",
    "narrate_history",
    "narrate_missing",
    "narrate_no_data",
    "narrate_plan_preview",
    "narrate_probability",
    "narrate_profile_update",
    "narrate_rank",
    "narrate_recommendation",
    "narrate_risks",
    "narrate_rule",
]
