"""省份规则包：批次级建模的公共实现（AGENTS.md §6.6 / DECISIONS.md ADR-006）。

铁律
----
1. **来源纪律**：任何规则数字必须带 ``source_url`` + ``source_quote`` + ``verified_year``；
   没有来源的数字不许写进代码。
2. **批次级分支**：一个省必然有多个批次，批次之间「平行 / 顺序」性质完全不同，
   校验与配额必须按 ``BatchRule.is_parallel`` 分支（ADR-006）：
   顺序志愿批次的第一志愿权重极高、第 2 志愿起近乎无效，
   **绝不允许套用平行志愿的冲稳保梯度配额**。
3. **假设必须可见**：未核实的维度一律写入 ``BatchRule.assumptions``，
   且带 assumptions 的批次 ``verified_status`` 不得为 ``PRIMARY``（由 tests/test_rules.py 强制）。
4. 本模块属 ``core/``：纯数据 + 纯函数，禁止 IO / DB / 网络 / LLM。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.models import (
    BatchRule,
    ModelParams,
    ProvinceRuleInfo,
    RuleViolation,
    Tier,
    VolunteerPlan,
)

# ---------------------------------------------------------------------------
# 违规码（可解释剔除/校验的依据，供 UI 与追问回答引用）
# ---------------------------------------------------------------------------
EXCEED_MAX_VOLUNTEERS = "EXCEED_MAX_VOLUNTEERS"  # 填报数超过该批次志愿上限
EMPTY_PLAN = "EMPTY_PLAN"  # 空志愿表
DUPLICATE_UNIT = "DUPLICATE_UNIT"  # 同一投档单位重复出现
DUPLICATE_GROUP = "DUPLICATE_GROUP"  # 院校专业组模式下同组重复（一个组只能填一次）
UNIT_TYPE_MISMATCH = "UNIT_TYPE_MISMATCH"  # 单位类型与批次不符
BATCH_MISMATCH = "BATCH_MISMATCH"  # 单位批次与批次规则不符
PROVINCE_MISMATCH = "PROVINCE_MISMATCH"  # 单位省份与规则不符
ADJUSTMENT_UNSET = "ADJUSTMENT_UNSET"  # 有调剂的批次未选择是否服从调剂
ADJUSTMENT_NOT_APPLICABLE = "ADJUSTMENT_NOT_APPLICABLE"  # 无调剂概念却填了服从调剂
INVALID_TIER_QUOTA = "INVALID_TIER_QUOTA"  # 批次配额定义非法（仅平行志愿批次适用）

_VALID_TIER_NAMES = (Tier.CHONG.value, Tier.WEN.value, Tier.BAO.value, Tier.DIAN.value)


def validate_tier_quota(quota: dict[str, float] | None) -> list[str]:
    """校验批次层配额定义，返回问题描述列表（空 = 合法）。"""
    if quota is None:
        return []
    problems: list[str] = []
    unknown = sorted(set(quota) - set(_VALID_TIER_NAMES))
    if unknown:
        problems.append(f"未知分层名: {', '.join(unknown)}")
    if any(v < 0 for v in quota.values()):
        problems.append("配额存在负值")
    total = sum(quota.values())
    if abs(total - 1.0) > 1e-6:
        problems.append(f"配额之和应为 1.0，实际 {total:.6f}")
    return problems


def distribute_quota(weights: dict[str, float], total: int) -> dict[Tier, int]:
    """按权重把 ``total`` 个志愿分配到各分层（最大余额法，结果确定可测）。

    仅用于**平行志愿**批次；顺序志愿批次不分配配额（见 ``StandardProvinceRule.default_quota``）。
    """
    if total < 0:
        raise ValueError("total 不能为负")
    unknown = sorted(set(weights) - set(_VALID_TIER_NAMES))
    if unknown:
        raise ValueError(f"未知分层名: {', '.join(unknown)}")
    if total == 0:
        return {Tier(name): 0 for name in _VALID_TIER_NAMES}
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        raise ValueError("配额权重之和必须为正")

    # 确定性顺序：权重降序 → 名称升序
    keys = sorted(weights, key=lambda k: (-weights[k], k))
    raw = {k: total * weights[k] / weight_sum for k in keys}
    base = {k: int(raw[k]) for k in keys}  # 权重非负 → 等价于 floor
    remainder = total - sum(base.values())
    if remainder > 0:
        frac_order = sorted(keys, key=lambda k: (-(raw[k] - base[k]), k))
        for k in frac_order[:remainder]:
            base[k] += 1
    return {Tier(name): base.get(name, 0) for name in _VALID_TIER_NAMES}


class ProvinceRule(ABC):
    """一个省的规则包。★ 持有 ``batches``（至少一个），批次之间规则不同（ADR-006）。"""

    province: str
    batches: list[BatchRule]
    #: 主批次（本科普通批 / 专业平行志愿主批次）：默认推荐与志愿表以此为基准
    main_batch_code: str

    # ---- 查询 ----
    def get_batch(self, batch_code: str) -> BatchRule:
        for batch in self.batches:
            if batch.batch_code == batch_code:
                return batch
        known = ", ".join(b.batch_code for b in self.batches)
        raise KeyError(f"{self.province} 不存在批次 {batch_code!r}；已定义批次：{known}")

    def main_batch(self) -> BatchRule:
        return self.get_batch(self.main_batch_code)

    def rule_info(self, batch: BatchRule) -> ProvinceRuleInfo:
        """生成志愿表用的规则快照（含核实状态，供 UI 显示"规则待核实"横幅）。"""
        return ProvinceRuleInfo(
            province=self.province,
            batch_code=batch.batch_code,
            batch_name=batch.batch_name,
            unit_type=batch.unit_type,
            max_volunteers=batch.max_volunteers,
            majors_per_group=batch.majors_per_group,
            has_major_adjustment=batch.has_major_adjustment,
            is_parallel=batch.is_parallel,
            verified_status=batch.verified_status,
            verified_year=batch.verified_year,
            source_url=batch.source_url,
        )

    # ---- 来源纪律自检 ----
    def source_problems(self) -> list[str]:
        """返回来源纪律问题清单（空 = 合规）。供 tests 与 M3 元数据接口复用。"""
        problems: list[str] = []
        if not self.batches:
            problems.append(f"{self.province}: 未定义任何批次")
        codes = [b.batch_code for b in self.batches]
        if len(set(codes)) != len(codes):
            problems.append(f"{self.province}: 批次编码重复")
        if self.main_batch_code not in codes:
            problems.append(f"{self.province}: main_batch_code 不在 batches 中")
        for b in self.batches:
            if not b.source_url:
                problems.append(f"{b.batch_code}: 缺 source_url")
            if not b.source_quote:
                problems.append(f"{b.batch_code}: 缺 source_quote（官方原文摘录）")
            if b.verified_year is None:
                problems.append(f"{b.batch_code}: 缺 verified_year")
            if b.max_volunteers <= 0:
                problems.append(f"{b.batch_code}: max_volunteers 必须为正")
            if b.assumptions and b.verified_status.value == "PRIMARY":
                problems.append(
                    f"{b.batch_code}: 存在 assumptions 却标 PRIMARY（假设必须降级核实状态）"
                )
            if not b.is_parallel and b.tiers_quota is not None:
                problems.append(f"{b.batch_code}: 顺序志愿批次不得定义 tiers_quota")
            for p in validate_tier_quota(b.tiers_quota):
                problems.append(f"{b.batch_code}: {p}")
            if b.has_major_adjustment and b.unit_type.value != "MAJOR_GROUP":
                problems.append(f"{b.batch_code}: 有专业调剂却非院校专业组模式")
            if not b.has_major_adjustment and b.majors_per_group is not None:
                problems.append(f"{b.batch_code}: 无调剂概念却声明了组内专业数")
        return problems

    # ---- 校验与配额（省份可覆写）----
    @abstractmethod
    def validate_plan(self, plan: VolunteerPlan, batch: BatchRule) -> list[RuleViolation]:
        """校验志愿表在该批次下是否合法。返回违规清单（空 = 通过）。"""

    @abstractmethod
    def default_quota(self, batch: BatchRule) -> dict[Tier, int]:
        """该批次的默认分层配额。顺序志愿批次返回空 dict（不适用）。"""


class StandardProvinceRule(ProvinceRule):
    """六省共用的通用实现：批次级结构校验 + 配额分配。

    省份文件只声明 ``batches``；若某省存在特殊规则，覆写对应方法即可。
    M2 的 ``risk.py`` 负责梯度/安全垫类检查（NO_SAFETY_NET / SAFETY_NOT_SAFE 等），
    本类的 ``validate_plan`` 只做**批次级结构**校验，避免职责重叠。
    """

    def validate_plan(self, plan: VolunteerPlan, batch: BatchRule) -> list[RuleViolation]:
        violations: list[RuleViolation] = []
        items = plan.items

        if not items:
            violations.append(RuleViolation(code=EMPTY_PLAN, message="志愿表为空"))

        # 1) 数量上限（平行 / 顺序批次都适用，但语义不同：顺序志愿第 2 志愿起几乎无效）
        if len(items) > batch.max_volunteers:
            violations.append(
                RuleViolation(
                    code=EXCEED_MAX_VOLUNTEERS,
                    message=(
                        f"{batch.batch_name} 最多 {batch.max_volunteers} 个志愿，"
                        f"当前 {len(items)} 个"
                    ),
                )
            )

        # 2) 单位省份 / 批次 / 类型一致性
        seen_units: set[str] = set()
        seen_groups: set[tuple[str, str | None]] = set()
        for item in items:
            unit = item.unit
            if unit.province != self.province:
                violations.append(
                    RuleViolation(
                        code=PROVINCE_MISMATCH,
                        message=f"{unit.unit_id} 省份 {unit.province} 与规则 {self.province} 不符",
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )
            if unit.batch != batch.batch_code:
                violations.append(
                    RuleViolation(
                        code=BATCH_MISMATCH,
                        message=f"{unit.unit_id} 批次 {unit.batch} 与 {batch.batch_code} 不符",
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )
            if unit.unit_type != batch.unit_type:
                violations.append(
                    RuleViolation(
                        code=UNIT_TYPE_MISMATCH,
                        message=(
                            f"{unit.unit_id} 投档单位类型 {unit.unit_type.value} "
                            f"与批次要求 {batch.unit_type.value} 不符"
                        ),
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )

            # 3) 同一投档单位不得重复
            if unit.unit_id in seen_units:
                violations.append(
                    RuleViolation(
                        code=DUPLICATE_UNIT,
                        message=f"{unit.unit_id} 重复填报",
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )
            seen_units.add(unit.unit_id)

            # 4) 院校专业组：一个组只能填一次（AGENTS.md §6.7 去重）
            if batch.unit_type.value == "MAJOR_GROUP":
                key = (unit.college_id, unit.group_code)
                if key in seen_groups:
                    violations.append(
                        RuleViolation(
                            code=DUPLICATE_GROUP,
                            message=(
                                f"院校专业组 {unit.college_id}/"
                                f"{unit.group_code or '-'} 重复填报（一个组只能填一次）"
                            ),
                            unit_id=unit.unit_id,
                            position=item.position,
                        )
                    )
                seen_groups.add(key)

            # 5) 服从调剂选项：有调剂概念的批次必须显式选择
            if batch.has_major_adjustment and item.obey_adjustment is None:
                violations.append(
                    RuleViolation(
                        code=ADJUSTMENT_UNSET,
                        message=(
                            f"{unit.unit_id} 未选择是否服从专业调剂"
                            "（院校专业组模式下这是退档生死线）"
                        ),
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )
            if not batch.has_major_adjustment and item.obey_adjustment is not None:
                violations.append(
                    RuleViolation(
                        code=ADJUSTMENT_NOT_APPLICABLE,
                        message=(
                            f"{unit.unit_id} 填了服从调剂，但 {batch.batch_name} "
                            "是专业+院校模式，不存在调剂概念"
                        ),
                        unit_id=unit.unit_id,
                        position=item.position,
                    )
                )

        # 6) 顺序志愿批次：**不做**冲稳保梯度配额校验（ADR-006）。
        #    "第一志愿必须是最想去的"是 planner 的生成约束，无法从志愿表本身判定，
        #    因此这里不产出违规；相关提示由 M2 的 risk.py 以风险码呈现。
        return violations

    def default_quota(self, batch: BatchRule) -> dict[Tier, int]:
        """平行志愿批次按批次配额（缺省回落 ModelParams.quota）分配；顺序志愿批次返回空。"""
        if not batch.is_parallel:
            return {}
        weights = batch.tiers_quota if batch.tiers_quota is not None else ModelParams().quota
        problems = validate_tier_quota(weights)
        if problems:
            raise ValueError(f"{batch.batch_code} tiers_quota 非法: {'; '.join(problems)}")
        return distribute_quota(weights, batch.max_volunteers)
