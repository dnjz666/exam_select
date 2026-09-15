"""天津市规则包（院校专业组模式，批次级 / ADR-006）。

核实记录（🟡 SECONDARY，转载源）：`docs/DOMAIN_RULES.md` §1.1/§1 来源
- 来源：中国教育在线转载天津招考资讯网
- URL：https://www.eol.cn/kaoshi/gaokao/zytb/202606/t20260615_2745179.shtml
- 官方渠道（待核实入口）：https://zyfz.zhaokao.net

原文要点：本科 A 阶段 50 个平行院校专业组志愿，B 阶段 25 个，两阶段征询志愿均为 25 个；
普通高职(专科)批 20 个，专科征询 10 个。

🚩 **红线（DOMAIN_RULES §1.3）**：天津升级为 `PRIMARY` 前，其推荐结果**不得用于真实填报**，
UI 必须显示「规则待核实」横幅。本包所有批次 `verified_status=SECONDARY`，
M3/M4 必须据此驱动横幅。
"""

from __future__ import annotations

from app.core.models import BatchRule, SubjectPool, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

TJ_URL = "https://www.eol.cn/kaoshi/gaokao/zytb/202606/t20260615_2745179.shtml"
TJ_OFFICIAL_URL = "https://zyfz.zhaokao.net"
#: 选考科目池来源：天津政务网（市政府门户）转市招委《2026年天津市普通高校招生工作规定》
#: 考试院官网（zhaokao.net）另有页面确认"6 科中选考 3 科"，但未列科目名，故仅作佐证。
TJ_POOL_URL = "https://www.tj.gov.cn/sy/tjxw/202605/t20260508_7294747.html"
TJ_POOL_OFFICIAL_URL = "http://www.zhaokao.net/gkck/system/2025/10/14/030009062.shtml"

_ASSUME_SUPPLEMENT = (
    "征询志愿批次的数量来自转载源要点；其志愿性质未逐字核实，按平行志愿框架建模"
)
_ASSUME_VOCATIONAL = (
    "高职(专科)批数量来自转载源要点；志愿性质与组内专业数未核实，按院校专业组模式建模"
)
_QUOTE_A = "本科 A 阶段 50 个平行院校专业组志愿。（转载源原文要点）"
_QUOTE_B = "本科 B 阶段 25 个平行院校专业组志愿。（转载源原文要点）"


class TianjinRule(StandardProvinceRule):
    province = "tianjin"
    main_batch_code = "tianjin.undergrad.a"

    batches = [
        BatchRule(
            batch_code="tianjin.undergrad.a",
            batch_name="本科A阶段（平行志愿）",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=50,
            majors_per_group=None,  # 转载源仅称"组内多个"，具体数未核实 → 不写数
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote=_QUOTE_A,
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=["组内专业数未核实（转载源仅称\u201c组内多个\u201d）"],
        ),
        BatchRule(
            batch_code="tianjin.undergrad.b",
            batch_name="本科B阶段（平行志愿）",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=25,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote=_QUOTE_B,
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=["组内专业数未核实（转载源仅称\u201c组内多个\u201d）"],
        ),
        BatchRule(
            batch_code="tianjin.undergrad.a.supplement",
            batch_name="本科A阶段征询志愿",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=25,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote="本科 A 阶段征询志愿 25 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_SUPPLEMENT],
        ),
        BatchRule(
            batch_code="tianjin.undergrad.b.supplement",
            batch_name="本科B阶段征询志愿",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=25,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote="本科 B 阶段征询志愿 25 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_SUPPLEMENT],
        ),
        BatchRule(
            batch_code="tianjin.vocational.regular",
            batch_name="普通高职(专科)批",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=20,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote="普通高职(专科)批 20 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_VOCATIONAL],
        ),
        BatchRule(
            batch_code="tianjin.vocational.supplement",
            batch_name="专科征询志愿",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=10,
            majors_per_group=None,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=TJ_URL,
            source_quote="专科征询志愿 10 个。（转载源原文要点）",
            verified_status=VerifiedStatus.SECONDARY,
            verified_year=2026,
            assumptions=[_ASSUME_VOCATIONAL],
        ),
    ]

    official_source_url = TJ_OFFICIAL_URL

    #: 3+3 选考科目池（AGENTS.md §8.1 Step 2）：6 选 3。
    #: ⚠️ 志愿规则是 SECONDARY（转载源），但科目池来源是政府门户转市招委文件 → PRIMARY-GOV。
    subject_pool = SubjectPool(
        province="tianjin",
        mode="6选3",
        choose=3,
        subjects=["物理", "化学", "生物", "思想政治", "历史", "地理"],
        source_url=TJ_POOL_URL,
        source_quote="等级性考试科目为思想政治、历史、地理、物理、化学、生物学6门，由考生自主选择其中3门参加考试。",
        verified_status=VerifiedStatus.PRIMARY_GOV,
        verified_year=2026,
        caveats=[
            "官方原文写\u201c生物学\u201d；本系统统一用\u201c生物\u201d，与招生计划选考要求字段口径一致",
            "降级理由：科目名取自天津政务网（市政府门户）转述市招委《2026年天津市普通高校招生工作规定》；"
            f"考试院官网 {TJ_POOL_OFFICIAL_URL} 确认\u201c6 科中选考 3 科\u201d但未列科目名，"
            "待取工作规定原文后升 PRIMARY",
        ],
    )
