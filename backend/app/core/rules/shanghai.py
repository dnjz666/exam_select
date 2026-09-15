"""上海市规则包（院校专业组模式，批次级 / ADR-006）。

核实记录（PRIMARY）：`docs/DOMAIN_RULES.md` §1.2.3 上海
- 来源：上海市教育考试院《上海市2026年普通高等学校招生志愿填报与投档录取实施办法》
  （沪教考院高招〔2026〕5号，2026-03-31）
- URL：https://www.shmeea.edu.cn/page/08000/20260402/20157.html

上海是全项目信息量最大的来源：除志愿数量外还给出**投档比例 1:1**、**同分排序 6 级位序**、
**调剂仅限组内**、**退档情形**——已落成 `BatchRule` 扩展字段。
"""

from __future__ import annotations

from app.core.models import BatchRule, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

SH_URL = "https://www.shmeea.edu.cn/page/08000/20260402/20157.html"

_QUOTE_REGULAR = (
    "（7）本科普通批次设置24个平行志愿。"
    "每个院校专业组志愿内设4个专业志愿。考生在每个院校专业组志愿中均须选择愿否服从专业志愿调剂。"
    "零志愿批次和本科普通批次按1:1比例投档。"
    "专业调剂录取只能在考生被投档的院校专业组内进行。"
)
_ASSUME_RECORD_ONLY = (
    "数量与志愿性质来自 `docs/DOMAIN_RULES.md` §1.2.2 核实记录表格（原文（1）(2)(5) 转述），"
    "未逐字摘录原文；组内专业数与调剂规则未核实"
)


class ShanghaiRule(StandardProvinceRule):
    province = "shanghai"
    main_batch_code = "shanghai.undergrad.regular"

    batches = [
        BatchRule(
            batch_code="shanghai.undergrad.regular",
            batch_name="本科普通批次",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=24,
            majors_per_group=4,
            has_major_adjustment=True,  # 组内服从调剂是保命选项
            is_parallel=True,
            tiers_quota=None,
            source_url=SH_URL,
            source_quote=_QUOTE_REGULAR,
            verified_status=VerifiedStatus.PRIMARY,
            verified_year=2026,
            admission_ratio="1:1",
            adjustment_scope="专业调剂录取只能在考生被投档的院校专业组内进行",
            tie_break_rules=[
                "第1位序：比较语文加数学两门合计成绩高低（原文摘录：6 级位序中的第 1 项）",
                "第6位序：比较考生志愿顺序，位序靠前者优先（原文摘录：6 级位序中的第 6 项）",
            ],
            # 退档情形原文未逐条摘录 → 留 None，绝不用常识补全
            withdrawal_clause=None,
        ),
        BatchRule(
            batch_code="shanghai.undergrad.advance",
            batch_name="本科提前批次（顺序志愿）",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=4,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=False,  # ★ 顺序志愿
            tiers_quota=None,
            source_url=SH_URL,
            source_quote="（3）本科提前批次设置4个顺序志愿。（原文要点转述，非逐字摘录）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_RECORD_ONLY],
        ),
        BatchRule(
            batch_code="shanghai.comprehensive",
            batch_name="综合评价批次",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=4,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=SH_URL,
            source_quote="综合评价批次设置4个平行志愿。（原文要点转述，非逐字摘录）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_RECORD_ONLY],
        ),
        BatchRule(
            batch_code="shanghai.zero",
            batch_name="零志愿批次",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=3,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=SH_URL,
            source_quote="零志愿批次设置3个平行志愿，按1:1比例投档。（原文要点转述，非逐字摘录）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_RECORD_ONLY],
        ),
        BatchRule(
            batch_code="shanghai.rural",
            batch_name="地方农村专项批次（顺序志愿）",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=4,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=False,
            tiers_quota=None,
            source_url=SH_URL,
            source_quote="地方农村专项批次设置4个顺序志愿。（原文要点转述，非逐字摘录）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_RECORD_ONLY],
        ),
    ]
