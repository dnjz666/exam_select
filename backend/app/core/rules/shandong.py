"""山东省规则包（专业(专业类)+学校模式，批次级 / ADR-006）。

核实记录（PRIMARY）：`docs/DOMAIN_RULES.md` §1.2.3 山东
- 来源：山东省教育招生考试院官网政策问答
- URL：https://www.sdzk.cn/NewsInfo.aspx?NewsID=5029 （2020-09-02 通知公告）
- URL：https://www.sdzk.cn/NewsInfo.aspx?NewsID=5413 （2021-06-23 政策问答）

已核实：普通类常规批"专业（专业类）+学校"平行志愿，1 个"专业+学校"=1 个志愿，
每次填报最多不超过 96 个（本科和专科都包含在内）。

⚠️ **遗留（M1 起记入 `docs/DOMAIN_RULES.md` §1.3）**：本条依据为 2020/2021 年官网问答，
数字长年稳定但**未取 2026 当年《录取工作意见》再核**；`assumptions` 已显式记录该风险
（verified_status 仍为 PRIMARY，因为来源确为考试院官网原文；年份偏差风险单列）。

未纳入：艺术类本科批统考/联考、体育类常规批（各 ≤ 60 个志愿）—— AGENTS.md §1.2 非目标。
"""

from __future__ import annotations

from app.core.models import BatchRule, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

SD_URL_NOTICE = "https://www.sdzk.cn/NewsInfo.aspx?NewsID=5029"
SD_URL_QA = "https://www.sdzk.cn/NewsInfo.aspx?NewsID=5413"

_QUOTE_REGULAR = (
    "志愿均实行以\"专业（专业类）+学校\"为单位的平行志愿模式，"
    "1个\"专业（专业类）+学校\"为1个志愿。"
    "考生每次填报志愿的数量最多不超过96个（本科和专科志愿都包含在内）。"
)


class ShandongRule(StandardProvinceRule):
    province = "shandong"
    main_batch_code = "shandong.regular"

    batches = [
        BatchRule(
            batch_code="shandong.regular",
            batch_name="普通类常规批专业(专业类)+学校平行志愿",
            unit_type=UnitType.MAJOR_COLLEGE,
            max_volunteers=96,
            majors_per_group=None,
            has_major_adjustment=False,
            is_parallel=True,
            tiers_quota=None,
            source_url=SD_URL_NOTICE,
            source_quote=_QUOTE_REGULAR,
            verified_status=VerifiedStatus.PRIMARY,
            verified_year=2026,
            assumptions=[],  # 无内容层假设：数量与"平行志愿"性质均来自官方原文
            caveats=[
                "依据为 2020-09-02 通知公告与 2021-06-23 政策问答，未取 2026 当年"
                "《山东省普通高校招生录取工作意见》再核年份；数字长年稳定，"
                "但年份适用性待补（DOMAIN_RULES §1.3 遗留待办）",
            ],
        ),
    ]
