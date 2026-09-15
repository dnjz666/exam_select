"""海南省规则包（院校专业组模式，批次级 / ADR-006）。

核实记录（🟡 SECONDARY，转载源）：`docs/DOMAIN_RULES.md` §1.1/§1 来源
- 来源：中国教育在线转载海南省教育厅
- URL：https://gaokao.eol.cn/hai_nan/dongtai/202606/t20260607_2742074.shtml
- 官方渠道（待核实入口）：https://ea.hainan.gov.cn

原文要点：本科普通批（含本科少数民族班）设 30 个院校专业组志愿，每个院校专业组内
设 6 个专业志愿和服从专业调剂志愿；本科提前普通类 6 个；高职（专科）批 10 个。

🚩 **红线（DOMAIN_RULES §1.3）**：海南升级为 `PRIMARY` 前，其推荐结果**不得用于真实填报**，
UI 必须显示「规则待核实」横幅。
"""

from __future__ import annotations

from app.core.models import BatchRule, SubjectPool, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

HN_URL = "https://gaokao.eol.cn/hai_nan/dongtai/202606/t20260607_2742074.shtml"
HN_OFFICIAL_URL = "https://ea.hainan.gov.cn"
#: 选考科目池来源：海南省教育厅《关于做好2026年海南省普通高等学校招生考试报名工作的通知》（考试局官网）
HN_POOL_URL = "http://ea.hainan.gov.cn/ywdt/ptgkyjszsb/202510/t20251025_3952951.html"

_ASSUME_NATURE = "志愿性质未逐字核实，按{nature}建模（转载源仅给出数量）"


class HainanRule(StandardProvinceRule):
    province = "hainan"
    main_batch_code = "hainan.undergrad.regular"

    batches = [
        BatchRule(
            batch_code="hainan.undergrad.regular",
            batch_name="本科普通批（含本科少数民族班）",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=30,
            majors_per_group=6,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=HN_URL,
            source_quote=(
                "本科普通批（含本科少数民族班）设 30 个院校专业组志愿，"
                "每个院校专业组内设 6 个专业志愿和服从专业调剂志愿。（转载源原文要点）"
            ),
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
        ),
        BatchRule(
            batch_code="hainan.undergrad.advance",
            batch_name="本科提前普通类",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=6,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=False,
            tiers_quota=None,
            source_url=HN_URL,
            source_quote="本科提前普通类 6 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_NATURE.format(nature="提前批惯例（顺序志愿）")],
        ),
        BatchRule(
            batch_code="hainan.vocational.regular",
            batch_name="高职（专科）批",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=10,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=HN_URL,
            source_quote="高职（专科）批 10 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_NATURE.format(nature="平行志愿")],
        ),
    ]

    official_source_url = HN_OFFICIAL_URL

    #: 3+3 选考科目池（AGENTS.md §8.1 Step 2）：6 选 3。
    #: ⚠️ 志愿规则是 SECONDARY（转载源），但科目池来源是考试局官网原文 → PRIMARY。
    subject_pool = SubjectPool(
        province="hainan",
        mode="6选3",
        choose=3,
        subjects=["物理", "化学", "生物", "思想政治", "历史", "地理"],
        source_url=HN_POOL_URL,
        source_quote=(
            "每位考生要从思想政治、历史、地理、物理、化学、生物学等6门普通高中学业水平"
            "选择性考试科目中，自主选择其中3个科目报考。"
        ),
        verified_status=VerifiedStatus.PRIMARY,
        verified_year=2026,
        caveats=[
            "官方原文写\u201c生物学\u201d（部分年份文件写\u201c生物\u201d）；"
            "本系统统一用\u201c生物\u201d，与招生计划选考要求字段口径一致",
        ],
    )
