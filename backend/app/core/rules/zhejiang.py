"""浙江省规则包（专业(类)+院校模式，批次级 / ADR-006）。

核实记录（PRIMARY）：`docs/DOMAIN_RULES.md` §1.2.3 浙江
- 来源：浙江省教育考试院《关于做好2026年普通高校招生网上填报志愿工作的通知》
- URL：https://www.zjzs.net/art/2026/6/13/art_156_12376.html

已核实：
- 普通类**专业平行志愿**分两段填报，每段 ≤ 80 个 → 平行志愿；
- 普通类**提前录取院校**设 5 个**院校传统（顺序）志愿**，每校 6 个专业志愿 + 专业服从调剂。

未纳入：艺术类统考批 / 体育类（各 ≤ 30 个志愿）—— 属 AGENTS.md §1.2 明确的非目标
（不做艺体专项规则），且其"平行/顺序"性质未从原文逐字核实，故不落码。
"""

from __future__ import annotations

from app.core.models import BatchRule, UnitType, VerifiedStatus
from app.core.rules.base import StandardProvinceRule

ZJ_URL = "https://www.zjzs.net/art/2026/6/13/art_156_12376.html"

_QUOTE_PARALLEL = "专业平行志愿分两段填报志愿，每段均可填报不超过80个志愿。"
_QUOTE_ADVANCE = (
    "提前录取院校设5个院校传统志愿，每所院校设6个专业志愿和专业服从调剂志愿。"
    "投档录取按一段线、二段线根据志愿顺序依次进行。"
)


class ZhejiangRule(StandardProvinceRule):
    province = "zhejiang"
    main_batch_code = "zhejiang.public.seg1"

    batches = [
        BatchRule(
            batch_code="zhejiang.public.seg1",
            batch_name="普通类第一段专业平行志愿",
            unit_type=UnitType.MAJOR_COLLEGE,
            max_volunteers=80,
            majors_per_group=None,
            has_major_adjustment=False,  # 专业+院校：无调剂概念（名师铁律：不存在退档调剂问题）
            is_parallel=True,
            tiers_quota=None,  # 回落 ModelParams.quota；批次级配额待 M2 回测标定
            source_url=ZJ_URL,
            source_quote=_QUOTE_PARALLEL,
            verified_status=VerifiedStatus.PRIMARY,
            verified_year=2026,
        ),
        BatchRule(
            batch_code="zhejiang.public.seg2",
            batch_name="普通类第二段专业平行志愿",
            unit_type=UnitType.MAJOR_COLLEGE,
            max_volunteers=80,
            majors_per_group=None,
            has_major_adjustment=False,
            is_parallel=True,
            tiers_quota=None,
            source_url=ZJ_URL,
            source_quote=_QUOTE_PARALLEL,
            verified_status=VerifiedStatus.PRIMARY,
            verified_year=2026,
        ),
        BatchRule(
            batch_code="zhejiang.advance.college",
            batch_name="普通类提前录取院校",
            unit_type=UnitType.MAJOR_GROUP,  # 院校传统志愿：单位=院校，组内 6 专业
            max_volunteers=5,
            majors_per_group=6,
            has_major_adjustment=True,
            is_parallel=False,  # ★ 顺序志愿：第 2 志愿起近乎无效，禁套冲稳保配额
            tiers_quota=None,  # 顺序志愿不使用配额（source_problems 强制）
            source_url=ZJ_URL,
            source_quote=_QUOTE_ADVANCE,
            verified_status=VerifiedStatus.PRIMARY,
            verified_year=2026,
        ),
    ]
