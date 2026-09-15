"""北京市规则包（院校专业组模式，批次级 / ADR-006）。

核实记录（🟡 PRIMARY-GOV）：`docs/DOMAIN_RULES.md` §1.2.3 北京
- 来源：首都之窗（北京市人民政府门户网站）转北京教育考试院，2026-06-11
- URL：https://www.beijing.gov.cn/fuwu/bmfw/sy/jrts/202606/t20260611_4695756.html

⚠️ **降级原因**：`bjeea.cn` 官网《志愿填报须知》未直接列出志愿数量，当前依据为市政府门户转述。
M1 需从《北京市2026年普通高等学校招生工作规定》原文再核，方可升为 PRIMARY。
（`assumptions` 已显式记录该降级理由，供 UI 徽标与审计使用。）

未纳入：本科提前批（原文仅在括号中排除"普通类B段"，未给出志愿数量与性质）→ 不落码。
"""

from __future__ import annotations

from app.core.models import BatchRule, SubjectPool, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

BJ_URL = "https://www.beijing.gov.cn/fuwu/bmfw/sy/jrts/202606/t20260611_4695756.html"
BJ_OFFICIAL_URL = "https://www.bjeea.cn/html/gkgz/tzgg/2026/0614/88216.html"
#: 选考科目池来源：《北京市2026年普通高等学校招生工作规定》（考试院官网原文）
BJ_POOL_URL = "https://www.bjeea.cn/html/gkgz/tzgg/2026/0505/88114.html"

_ASSUME_DOWNGRADE = (
    "来源为市政府门户转述北京教育考试院（PRIMARY-GOV）；考试院官网《志愿填报须知》"
    "未直接列出志愿数量，待《北京市2026年普通高等学校招生工作规定》原文复核后升 PRIMARY"
)


class BeijingRule(StandardProvinceRule):
    province = "beijing"
    main_batch_code = "beijing.undergrad.regular"

    batches = [
        BatchRule(
            batch_code="beijing.undergrad.regular",
            batch_name="本科普通批",
            unit_type=UnitType.MAJOR_GROUP,
            max_volunteers=30,
            majors_per_group=6,
            has_major_adjustment=True,
            is_parallel=True,
            tiers_quota=None,
            source_url=BJ_URL,
            source_quote=(
                "本科普通批实行平行志愿，设置30个志愿。"
                "本科志愿以院校专业组为志愿设置单位，一个院校专业组即为一个独立的志愿，"
                "每个志愿一般设置6个专业和1个\u201c是否服从专业组内调剂\u201d选项"
                "（本科提前批普通类B段除外）。"
            ),
            verified_status=VerifiedStatus.PRIMARY_GOV,
            verified_year=2026,
            assumptions=[_ASSUME_DOWNGRADE],
            adjustment_scope="是否服从专业组内调剂",
        ),
        BatchRule(
            batch_code="beijing.vocational.regular",
            batch_name="专科普通批",
            unit_type=UnitType.MAJOR_COLLEGE,  # 原文：1 校 1 专业 → 专业+院校粒度
            max_volunteers=20,
            majors_per_group=None,
            has_major_adjustment=False,
            is_parallel=True,
            tiers_quota=None,
            source_url=BJ_URL,
            source_quote="专科普通批设置20个平行志愿，每个志愿设置1所院校1个专业。",
            verified_status=VerifiedStatus.PRIMARY_GOV,
            verified_year=2026,
            assumptions=[_ASSUME_DOWNGRADE],
        ),
    ]

    # 供 M1 待办引用：升 PRIMARY 的原文入口
    official_source_url = BJ_OFFICIAL_URL

    #: 3+3 选考科目池（AGENTS.md §8.1 Step 2）。
    #: ⚠️ 本科选考池为 6 门；专科批另用学考合格考 8 门作资格要求（含信息技术/通用技术），
    #:    那是专科资格要求**不是**本科选考池，不得混入。
    subject_pool = SubjectPool(
        province="beijing",
        mode="6选3",
        choose=3,
        subjects=["物理", "化学", "生物", "思想政治", "历史", "地理"],
        source_url=BJ_POOL_URL,
        source_quote="学考等级考科目为思想政治、历史、地理、物理、化学、生物6门，由考生自主选择3门参加考试。",
        verified_status=VerifiedStatus.PRIMARY,
        verified_year=2026,
        caveats=[
            "专科（高职）批以学考合格考 8 门（含信息技术、通用技术）作资格要求，"
            "属专科资格要求，不进入本科选考科目池",
        ],
    )
