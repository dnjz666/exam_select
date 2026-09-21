"""真实数据适配器（M6，AGENTS.md §4.2 ``etl/loaders/``）。

当前已接入：**浙江省**（本项目默认省份，AGENTS.md §1.2 的端到端闭环省份）。
其余五省仍走 ``etl/synthetic.py`` 的**模拟数据**（用户 2026-09 明确：先接浙江真实数据，
其余先用模拟数据）。

数据来源与口径
--------------
全部来自浙江省教育考试院（www.zjzs.net）**公开发布物**，采集与解析脚本见
``scripts/collect_zj_scorelines.py`` / ``parse_zj_compilation_pdf.py`` /
``collect_zj_score_segment.py``，每个文件都在 ``data/raw/zhejiang/manifest.json``
里登记了来源 URL 与 sha256。

============  ==================================================  ==============
年份          来源                                                用途
============  ==================================================  ==============
2023–2025     《浙江省普通高校招生投档及专业录取情况》合编 PDF      历年投档/录取（含选考要求）
2024          年度「普通类第一段平行投档分数线表」.xls              2024 独立来源交叉校验
2026          年度「普通类第一段平行投档分数线表」.xls              **填报年**投档单位与计划数
2026          官方《成绩分数段表（总分）》PDF                      一分一段表（位次法地基）
============  ==================================================  ==============

三个必须说清楚的建模决定（详见 ``docs/DECISIONS.md`` ADR-015）
------------------------------------------------------------
1. **`is_synthetic` 仍然表示"这一行的数字是不是真实投档数据"**：凡来自上述官方文件的行
   一律 ``is_synthetic=0``。M6 只在两处使用模拟值，并逐行如实标注：
   * ``colleges.tuition`` —— 官方投档表不含学费 → 该字段 **留空**（不编造），
     ``AdmissionUnit.tuition`` 写 0；
   * 2023–2025 的 ``score_rank_table`` —— 无官方分数段表 → 由**官方一段线 + 官方累计人数
     锚定**的模拟分布生成，行标记 ``is_synthetic=1``（2026 为官方原文，``is_synthetic=0``）。

2. **跨年单位对齐靠「院校代号 + 专业名」而不是「专业代号」**：浙江的 ``专业代号`` 每年重排
   （2025 年 0001 的专业代号 001–041 在 2026 年对应完全不同的专业），而 ``unit_key`` 必须
   跨年稳定，否则历年位次接不到一起。因此 ``unit_key`` 形如
   ``zhejiang-{院校代号}-NA-{专业链标识}``，专业链标识由专业名归一化后取稳定摘要。
   同一院校同名专业的两个不同专业代号会拆成两条链（``-2`` 后缀），不静默合并。

3. **绝不为了"看起来完整"而补造数字**：2021/2022 年的投档表没有选考科目要求，
   本加载器**不导入**它们（宁可少两年历史，也不让没有选考要求的行进入推荐结果）。
   ``load_zhejiang()`` 返回的 ``gaps`` 会如实列出所有缺口。
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, NamedTuple

import xlrd

from app.core.major_taxonomy import (
    LEVEL_BENKE,
    LEVEL_ZHUANKE,
    TaxonomyStatus,
    classify_major,
)
from app.etl import catalog

PROVINCE = "zhejiang"
BATCH = "zhejiang.public.seg1"  # 普通类第一段专业平行志愿（ZhejiangRule.main_batch_code）
TRACK = "综合"
UNIT_TYPE = "MAJOR_COLLEGE"  # 专业(类)+院校：无调剂概念

#: 填报年（与 ``etl.synthetic.CURRENT_YEAR`` 一致；这里独立列出以免反向依赖模拟数据模块）
TARGET_YEAR = 2026
#: 用于**线上预测**的历史年（2023–2025 有选考科目要求，2021/2022 没有）
HISTORY_YEARS: tuple[int, ...] = (2023, 2024, 2025)
#: 2024 年同时存在合编 PDF 与年度 .xls 两个独立官方来源 → 交叉校验年
CROSS_CHECK_YEAR = 2024
#: 年度一段表 .xls 的年份（2023/2025 无独立 .xls，只有合编 PDF）
XLS_YEARS: tuple[int, ...] = (2024, 2026)

NO_HISTORY_YEAR = 0  # 该专业链在该年没有投档记录


def _source(*parts: str) -> str:
    """``real://`` 前缀标记真实数据来源（可审计；与 synthetic:// 同构）。"""
    return "real://exam_select/etl/loaders/zhejiang.py?" + "&".join(parts)


SOURCE_COMPILATION = "zjzs.net 合编《浙江省普通高校招生投档及专业录取情况》PDF→CSV"
SOURCE_XLS = "zjzs.net 年度《浙江省普通高校招生普通类第一段平行投档分数线表》.xls"
SOURCE_SEGMENT_2026 = "zjzs.net《浙江省2026年普通高校招生成绩分数段表(总分)》PDF"
SOURCE_SEGMENT_SYNTH = "以官方一段线与官方累计人数锚定的模拟分数分布（M6：无官方分数段表）"


# ---------------------------------------------------------------------------
# 0) 文本归一
# ---------------------------------------------------------------------------
_BRACKET = re.compile(r"[（(][^（()）]*[)）]")
_SPACE = re.compile(r"[\s\u3000]+")
_PUNCT = str.maketrans({"（": "(", "）": ")", "，": ",", "、": ",", "“": '"', "”": '"', "：": ":"})


def norm_name(text: str) -> str:
    """专业名归一：全/半角括号统一、去空白。用于跨年同名判定。"""
    return _SPACE.sub("", (text or "").translate(_PUNCT)).strip()


def base_name(text: str) -> str:
    """专业名"基名"：去掉所有括号及其内容（``计算机类(中外合作办学)`` → ``计算机类``）。

    浙江招生专业名里括号内容多为方向/办学类型（中外合作、荣誉班、双学位），
    基名相同通常就是同一个专业的延续。
    """
    normalized = (text or "").translate(_PUNCT)
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = _BRACKET.sub("", normalized)
    return _SPACE.sub("", normalized).strip()


def slug_of(text: str, *, salt: str = "") -> str:
    """稳定短标识：``sha1(salt + 归一化文本)[:10]``（跨年、跨进程一致）。"""
    digest = hashlib.sha1(f"{salt}|{norm_name(text)}".encode("utf-8")).hexdigest()
    return digest[:10]


# ---------------------------------------------------------------------------
# 1) 源数据读取
# ---------------------------------------------------------------------------
class SourceRow(NamedTuple):
    """一行"某院校某专业某年"的投档记录（已归一，来自任一官方来源）。"""

    year: int
    college_code: str
    college_name: str
    college_province: str
    college_city: str
    major_code: str  # 浙江专业代号（仅当年有效）
    major_name: str
    subject_mode: str  # all_of | any_of | none | ""
    subject_subjects: tuple[str, ...]
    plan_count: int
    duration: int | None
    min_score: int | None
    min_rank: int | None
    avg_score: int | None
    data_quality: str  # OK | MISSING_RANK | COLLECTED
    source_url: str

    @property
    def name_key(self) -> str:
        return norm_name(self.major_name)

    @property
    def base_key(self) -> str:
        return base_name(self.major_name)


def _int(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def read_annual_xls(path: Path, year: int, *, source_url: str) -> list[SourceRow]:
    """读年度「普通类第一段平行投档分数线表」.xls。

    官方列：``学校代号 | 学校名称 | 专业代号 | 专业名称 | 计划数 | 分数线 | 位次``。
    表尾注释行（"注：位次栏目为空的…"）与合计行**没有学校代号**，天然被跳过。
    """
    sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
    header = [str(sheet.cell_value(0, col)).strip() for col in range(sheet.ncols)]
    if header[:7] != ["学校代号", "学校名称", "专业代号", "专业名称", "计划数", "分数线", "位次"]:
        raise ValueError(f"{path.name}: 表头与预期不符 {header}")

    rows: list[SourceRow] = []
    for index in range(1, sheet.nrows):
        code = re.sub(r"\D", "", str(sheet.cell_value(index, 0)).strip())
        if not code:
            continue
        name = str(sheet.cell_value(index, 1)).strip()
        major_code = re.sub(r"\D", "", str(sheet.cell_value(index, 2)).strip()).zfill(3)
        major_name = str(sheet.cell_value(index, 3)).strip()
        plan = _int(sheet.cell_value(index, 4))
        score = _int(sheet.cell_value(index, 5))
        rank = _int(sheet.cell_value(index, 6))
        if not name or not major_name or not plan:
            continue
        rows.append(
            SourceRow(
                year=year,
                college_code=code.zfill(4),
                college_name=name,
                college_province="",
                college_city="",
                major_code=major_code,
                major_name=major_name,
                subject_mode="",  # ★ 年度一段表不含选考科目要求（不可编造）
                subject_subjects=(),
                plan_count=plan,
                duration=None,
                min_score=score,
                min_rank=rank,
                avg_score=None,
                # 官方表尾原文：「位次栏目为空的，表示该学校专业本轮投档人数未满」
                data_quality="OK" if rank else "MISSING_RANK",
                source_url=source_url,
            )
        )
    return rows


def read_compilation_csv(path: Path, year: int, *, source_url: str) -> list[SourceRow]:
    """读合编 PDF 解析出的规范化 CSV（含选考科目要求、学制、平均分、一/二段）。"""
    rows: list[SourceRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            plan = _int(raw.get("plan_count"))
            if not plan:
                continue
            mode = (raw.get("subject_mode") or "").strip()
            subjects = tuple(
                part for part in (raw.get("subject_subjects") or "").replace(" ", "").split(",") if part
            )
            if mode not in ("all_of", "any_of", "none"):
                mode, subjects = "", ()  # 解析不出来的选考要求一律留空，不猜
            seg1_score, seg1_rank = _int(raw.get("seg1_min_score")), _int(raw.get("seg1_min_rank"))
            seg2_score, seg2_rank = _int(raw.get("seg2_min_score")), _int(raw.get("seg2_min_rank"))
            quality = (raw.get("data_quality") or "").strip() or "OK"

            # ★ 一段优先：一段有完整（分+位次）记录时，用一段；否则退到二段。
            #   同一院校专业只产生**一条**历史行（unit_key 跨年唯一，重复会破坏回测口径）。
            if seg1_rank:
                min_score, min_rank = seg1_score, seg1_rank
            elif seg2_rank:
                min_score, min_rank = seg2_score, seg2_rank
            else:
                min_score, min_rank = (seg1_score or seg2_score), None
            if min_rank is None:
                quality = "MISSING_RANK"
            elif quality not in ("OK", "COLLECTED"):
                quality = "OK"

            rows.append(
                SourceRow(
                    year=year,
                    college_code=str(raw.get("college_code") or "").zfill(4),
                    college_name=(raw.get("college_name") or "").strip(),
                    college_province=(raw.get("college_province") or "").strip(),
                    college_city=(raw.get("college_city") or "").strip(),
                    major_code="",  # 合编 PDF 不含专业代号
                    major_name=(raw.get("major_name") or "").strip(),
                    subject_mode=mode,
                    subject_subjects=subjects,
                    plan_count=plan,
                    duration=_int(raw.get("duration")),
                    min_score=min_score,
                    min_rank=min_rank,
                    avg_score=_int(raw.get("avg_score")),
                    data_quality=quality,
                    source_url=source_url,
                )
            )
    return rows


def read_score_segment_csv(path: Path, year: int) -> list[tuple[int, int, int]]:
    """读官方分数段表 CSV → ``[(score, count_at_score, cumulative_rank)]``（分数降序）。"""
    rows: list[tuple[int, int, int]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            score = _int(raw["score"])
            count = _int(raw["count_at_score"])
            cumulative = _int(raw["cumulative_rank"])
            if score is None or count is None or cumulative is None:
                continue
            rows.append((score, count, cumulative))
    rows.sort(key=lambda row: -row[0])
    return rows


# ---------------------------------------------------------------------------
# 2) 专业链（跨年对齐的实体）
# ---------------------------------------------------------------------------
@dataclass
class MajorChain:
    """一个「院校 + 专业」跨年实体。

    ``entries`` 是历年该专业链的投档记录（每年至多一条），``slug`` 进入 ``unit_key``。
    """

    college_code: str
    base_key: str
    slug: str
    ordinal: int = 1
    exact_names: set[str] = field(default_factory=set)
    entries: dict[int, SourceRow] = field(default_factory=dict)

    def years(self) -> list[int]:
        return sorted(self.entries)

    def merits(self) -> int:
        """专业链可信度：有记录的年份数 × 10 − 顺序号（顺序号越小越优先）。"""
        return len(self.entries) * 10 - self.ordinal


def _merge_duplicates(rows: list[SourceRow]) -> tuple[dict[int, SourceRow], list[str]]:
    """同一专业链在同一年出现多行时的合并：一段有完整位次的记录优先。"""
    problems: list[str] = []
    merged: dict[int, SourceRow] = {}
    for row in rows:
        existing = merged.get(row.year)
        if existing is None:
            merged[row.year] = row
            continue
        better = (row.min_rank is not None) and (existing.min_rank is None)
        worse = (existing.min_rank is not None) and (row.min_rank is None)
        if better:
            problems.append(
                f"{row.college_code}/{row.major_name}@{row.year}: 同年两条记录，取有一段位次的一条"
            )
            merged[row.year] = row
        elif worse:
            problems.append(
                f"{row.college_code}/{row.major_name}@{row.year}: 同年两条记录，保留有一段位次的一条"
            )
        else:
            problems.append(
                f"{row.college_code}/{row.major_name}@{row.year}: 同年两条都有位次，取计划数较大的一条"
            )
            if row.plan_count > existing.plan_count:
                merged[row.year] = row
    return merged, problems


def _attach_target_year(
    target_rows: list[SourceRow],
    chains: list[MajorChain],
    *,
    target_year: int,
    notes: list[str],
) -> dict[str, MajorChain]:
    """把**填报年**的行挂接到既有专业链上；挂不上的按"当年新增专业"新建链。

    匹配优先级（确定性，不含随机与启发式打分）：
    1. **全名精确**：该院校存在全名相同的链 → 用**最优链**（历史年数多者优先，再比 slug）；
    2. **基名唯一**：该院校该基名只有一条链且它还没有当年记录 → 用它（专业名加了
       方向/办学类型括号的延续，如 ``工科试验班`` → ``工科试验班(智慧城市与建筑工程)``）；
    3. 其余 → **新建链**：这条链没有历史，概率模型会走 Step 0 类比并标注低置信度
       （名师铁律 9：无历史 ≠ 不能报，但绝不虚构位次）。
    """
    exact_lookup: dict[tuple[str, str], list[MajorChain]] = defaultdict(list)
    base_lookup: dict[tuple[str, str], list[MajorChain]] = defaultdict(list)
    for chain in chains:
        for name in chain.exact_names:
            exact_lookup[(chain.college_code, name)].append(chain)
        base_lookup[(chain.college_code, chain.base_key)].append(chain)

    attached: dict[str, MajorChain] = {}
    for row in sorted(target_rows, key=lambda r: (r.college_code, r.major_code)):
        key = f"{row.college_code}-{row.major_code}"
        candidates = [c for c in exact_lookup.get((row.college_code, row.name_key), []) if target_year not in c.entries]
        chain: MajorChain | None = None
        if len(candidates) >= 1:
            chain = max(candidates, key=lambda c: (c.merits(), c.slug))
        else:
            base_candidates = base_lookup.get((row.college_code, row.base_key), [])
            if len(base_candidates) == 1 and target_year not in base_candidates[0].entries:
                chain = base_candidates[0]
        if chain is None:
            bucket = base_lookup[(row.college_code, row.base_key)]
            ordinal = len(bucket) + 1
            base_slug = slug_of(row.base_key, salt=row.college_code)
            chain = MajorChain(
                college_code=row.college_code,
                base_key=row.base_key,
                slug=base_slug if ordinal == 1 else f"{base_slug}-{ordinal}",
                ordinal=ordinal,
            )
            chains.append(chain)
            bucket.append(chain)
            notes.append(
                f"{row.college_code}/{row.major_name}: {target_year} 年新增（无历史链），走类比回退"
            )
        chain.entries[target_year] = row
        chain.exact_names.add(row.name_key)
        attached[key] = chain
    return attached




# ---------------------------------------------------------------------------
# 3) 数据装配
# ---------------------------------------------------------------------------
@dataclass
class RealZhejiangDataset:
    """一批可直接入库的真实数据（行结构与 ``synthetic.SyntheticDataset`` 对齐）。"""

    province: str = PROVINCE
    college_rows: list[dict] = field(default_factory=list)
    major_rows: list[dict] = field(default_factory=list)
    admission_units: list[dict] = field(default_factory=list)
    admission_plans: list[dict] = field(default_factory=list)
    admission_history: list[dict] = field(default_factory=list)
    score_rank_table: list[dict] = field(default_factory=list)
    province_year_stats: list[dict] = field(default_factory=list)
    chains: list[MajorChain] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        return {
            "colleges": len(self.college_rows),
            "majors": len(self.major_rows),
            "score_rank_table": len(self.score_rank_table),
            "province_year_stats": len(self.province_year_stats),
            "admission_units": len(self.admission_units),
            "admission_plans": len(self.admission_plans),
            "admission_history": len(self.admission_history),
        }

    def taxonomy_counts(self) -> dict[str, int]:
        """专业目录归属回填结果（ADR-018）——按判定来源计数，供审计与回归。

        ★ ``majors_without_discipline`` 是**刻意保留**的诚实缺口：
        试验班大类招生只定到门类，另有极少数新专业名无法归类。
        它们不参与"同一专业类"打分档，但**绝不用猜测填充**。
        """
        by_status: Counter[str] = Counter()
        without_discipline = 0
        without_category = 0
        for row in self.major_rows:
            taxonomy = classify_major(row["name"])
            by_status[taxonomy.status.value] += 1
            if not taxonomy.has_discipline:
                without_discipline += 1
            if not taxonomy.is_classified:
                without_category += 1
        return {
            "majors_total": len(self.major_rows),
            "majors_without_discipline": without_discipline,
            "majors_without_category": without_category,
            **{f"status_{k}": v for k, v in sorted(by_status.items())},
        }

    def digest(self) -> str:
        """内容摘要（幂等自检用；与 synthetic.SyntheticDataset.digest 同口径）。"""
        payload = json.dumps(
            {
                "units": sorted(row["unit_id"] for row in self.admission_units),
                "history": sorted(
                    f"{row['unit_key']}@{row['year']}:{row['min_rank']}"
                    for row in self.admission_history
                ),
                "plans": sorted(
                    f"{row['unit_key']}@{row['year']}:{row['plan_count']}"
                    for row in self.admission_plans
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()


#: 历年普通类一段线（用于锚定模拟分数分布与识别"未满"记录）。
#: 来源：浙江省教育考试院历年《各类别分数线》公布（本仓库 manifest.json 的 2021/2022/
#: 2024/2026 年度表与 2023–2025 合编 PDF 内《各类别分段线》页）。
SEGMENT_LINE: dict[int, tuple[int, str]] = {
    2023: (488, "浙江省教育考试院《2023年浙江省普通高校招生各类别分数线》"),
    2024: (492, "浙江省教育考试院《2024年浙江省普通高校招生各类别分数线》"),
    2025: (490, "浙江省教育考试院《2025年浙江省普通高校招生各类别分数线》"),
    2026: (494, "浙江省教育考试院《2026年浙江省普通高校招生各类别分数线》"),
}

#: 历年**普通类一段线上线人数**（官方口径：一段线对应的累计人数）。
#:
#: ★ 这是位次归一化的分母（AGENTS.md §6.1），**历年必须是同一口径**，否则跨年比较
#: 会凭空放大或缩小。M6 实测教训：一度用"整张分数段表的最低分累计人数"当分母，
#: 结果 2026 是 292,753（官方表最低分 266 分）而模拟的 2023 只有 166,000（表只到 488 分），
#: 同一位次的含金量被凭空放大 1.7 倍 → 跨年位次完全不可比。改用**一段线上线人数**后口径统一。
#:
#: 数据来源：
#: * 2026 = 184,816 —— 官方《成绩分数段表（总分）》494 分累计人数，**原文**；
#: * 2023 = 175,424 —— 浙江省教育考试院公布（一段线 488 分，官方报道
#:   「浙江2023年高考一段线上175424人」）；
#: * 2025 = 189,111 —— 官方 2026 分数段表中 **490 分**（2025 年一段线）的累计人数
#:   （同一张官方表可同时读出相邻年份同分段的累计人数，是可得的最接近口径）；
#: * 2024 = 178,041 —— 由 175,424 / 184,816 / 189,111 三点最小二乘拟合估计
#:   （拟合值 176,352，取本仓库 2024 合编 PDF 一段投档位次上限 178,041 作为保守上界），
#:   ``is_synthetic=1``，属"无官方原文时用相邻年份内插"的可审计估计。
SEGMENT1_CUMULATIVE: dict[int, int] = {
    2023: 175_424,
    2024: 178_041,
    2025: 189_111,
}
#: 官方口径说明（写进 source_url 与 gap 说明，便于审计）
SEGMENT1_SOURCE: dict[int, str] = {
    2023: "浙江省教育考试院公布：2023 年普通类一段线上 175,424 人（一段线 488）",
    2024: "由 2023/2025/2026 官方一段线上线人数线性拟合估计（保守取本仓库 2024 合编位次上限）",
    2025: "官方《浙江省2026年普通高校招生成绩分数段表(总分)》490 分（2025 一段线）累计人数",
}

#: 模拟分数分布生成的分数区间（不含 2026 官方表的 693–266 全区间）
_SYNTH_SCORE_HIGH = 750
_SYNTH_SCORE_LOW = 266
#: 模拟分布的"总考生数"基准（浙江普通类量级，用于生成尾部；非官方值，故整表标 is_synthetic=1）
_SYNTH_TOTAL_BASE = 295_000


def _empirical_score_table(
    year: int,
    observations: list[tuple[int, int]],
    anchor_rank: int,
) -> list[tuple[int, int, int]] | None:
    """由**当年官方投档记录**直接导出的"分数 → 累计位次"表（无官方分数段表时的首选）。

    核心式（对每个分数 s）::

        U(s)          = max{ min_rank : min_score >= s }        # 观测上界（严格单调）
        cumulative(s) = max( running_max(U)(s), 官方一段线上线人数（仅当 s <= 一段线） )

    为什么这样定义就**天然自洽**（不必事后校验、也不会与观测冲突）：

    * 每条投档记录都是官方发布的「该专业最低分 + 对应位次」，因此"考到 s 分及以上的人，
      位次不会好于 U(s)"是**观测事实**（取的是**最大**位次，天然是上界）；
    * 在分数降序扫描时对 U 取 running max → cumulative 天然单调不减，不需要保序回归修补；
    * 位次 r 落在区间 ``(cumulative(s+1), cumulative(s)]`` 时反查必然得回 s：
      因为 ``cumulative(s) >= min_rank`` 且 ``cumulative(s+1) <= U(s+1) < min_rank``。

    两点必须如实标注的局限（写进 ``source_url`` 与 gap 说明）：

    1. 观测只覆盖**有投档的专业**，所以这是"录取口径"的近似曲线，不等于考试院发布的
       全体考生一分一段表；整表 ``is_synthetic=1``；
    2. 高于当年最高投档分的区间没有观测，累计位次取最低观测上界并保证严格递增（外推）。
    """
    if not observations:
        return None
    # U(s) = 该分数及以上记录中的**最大**位次（观测上界；用 max 而非 min 才单调）
    upper_by_score: dict[int, int] = {}
    for rank, score in observations:
        if rank <= 0:
            continue
        upper_by_score[score] = max(upper_by_score.get(score, rank), rank)
    if len(upper_by_score) < 20:  # 观测分数点太少，不足以支撑整表
        return None

    scores = list(range(_SYNTH_SCORE_HIGH, _SYNTH_SCORE_LOW - 1, -1))
    known = [score for score in scores if score in upper_by_score]
    top_score = max(known)
    top_rank = min(upper_by_score[score] for score in known)
    line = SEGMENT_LINE[year][0]

    rows: list[tuple[int, int, int]] = []
    previous = 0
    running = top_rank
    for score in scores:
        if score in upper_by_score:
            running = max(running, upper_by_score[score])
        value = running
        if score <= line:
            value = max(value, anchor_rank)  # 一段线以下累计位次至少等于官方上线人数
        value = max(value, previous + 1)  # 严格递增（count_at_score >= 1）
        rows.append((score, value - previous, value))
        previous = value
    # 表底累计位次即"该表覆盖的最低分对应的累计人数"（官方 total_candidates 口径）
    return rows


def _gaussian_score_table(year: int, anchor_rank: int) -> list[tuple[int, int, int]]:
    """兜底方案：光滑的正态型"分数—累计人数"曲线，在官方一段线处锚定。

    仅在**没有任何当年观测点**时使用（例如某年数据整体缺失）。整表 ``is_synthetic=1``。
    """
    line = SEGMENT_LINE[year][0]
    scores = list(range(_SYNTH_SCORE_HIGH, _SYNTH_SCORE_LOW - 1, -1))
    mean, sd = 470.0, 95.0
    total = sum(math.exp(-0.5 * ((score - mean) / sd) ** 2) for score in scores)
    raw = [math.exp(-0.5 * ((score - mean) / sd) ** 2) / total * _SYNTH_TOTAL_BASE for score in scores]
    above = sum(count for score, count in zip(scores, raw) if score >= line)
    scale = anchor_rank / above if above else 1.0

    rows: list[tuple[int, int, int]] = []
    cumulative = 0
    for score, count in zip(scores, raw):
        value = max(1, int(round(count * scale)))
        if score == line:
            # ★ 精确闭合：一段线上累计人数必须**精确等于**官方值（归一化分母不允许有舍入漂移）
            value = max(1, anchor_rank - cumulative)
            cumulative = anchor_rank
        else:
            cumulative += value
        rows.append((score, value, cumulative))
    return rows


def _years_with_official_table(root: Path) -> dict[int, Path]:
    """扫出已解析的官方分数段表 CSV：``zhejiang_score_segment_{year}.csv``。"""
    found: dict[int, Path] = {}
    for path in sorted((root / "data" / "normalized" / PROVINCE).glob("zhejiang_score_segment_*.csv")):
        match = re.search(r"score_segment_(\d{4})\.csv$", path.name)
        if match:
            found[int(match.group(1))] = path
    return found


def _college_meta_from_catalog() -> dict[str, dict]:
    """用 ``etl/catalog.py``（人工维护的真实院校名册）补充层次标签。

    ★ 这是 M6 里**唯一**的"模拟侧"院校元数据来源：真实投档表不发布 985/211 标签，
    但没有层次标签，``scoring.level_score`` 与 ``probability`` 的 Step 0 类比池都会失效。
    因此只在**院校名精确命中**时补标签（418 所人工名册覆盖了全部 985/211 与主要省属校），
    未命中的院校一律留空 —— 宁可不全，不可编造。
    """
    meta: dict[str, dict] = {}
    for college in catalog.iter_colleges():
        meta[college.name] = {
            "tier": college.tier,
            "college_type": college.college_type,
            "province": college.province,
            "city": college.city,
        }
    return meta


_LEVEL_TAGS = {
    "985": ["985", "211", "双一流"],
    "211": ["211", "双一流"],
    "SY": ["双一流"],
}
#: 官方院校名后缀 → 属性（原文标注，非推断）
_NAME_SUFFIX = {
    "一流大学建设高校": ("level", ["985", "211", "双一流"]),
    "一流学科建设高校": ("level", ["双一流"]),
    "省重点建设高校": ("affiliation", "省重点建设高校"),
    "民办学校": ("is_public", False),
    "独立学院": ("is_public", False),
}


#: 省份中文名 → 本系统省份键（``RULES`` 的键；与 ``catalog`` 的英文键一致）。
#: 为什么必须归一：官方投档表里的"院校所在地"是**中文**（"浙江·杭州"），而模拟数据与
#: 规则包用的是英文键（``zhejiang``）。不归一会导致同一所院校在库里两个写法并存，
#: 概率模型 Step 0 的类比池 ``analog_key(college_province, ...)`` 也会被拆成两桶。
#: 本表只做**名称归一**，不新增任何规则数字。
_PROVINCE_KEY: dict[str, str] = {
    "北京": "beijing",
    "天津": "tianjin",
    "河北": "hebei",
    "山西": "shanxi",
    "内蒙古": "neimenggu",
    "辽宁": "liaoning",
    "吉林": "jilin",
    "黑龙江": "heilongjiang",
    "上海": "shanghai",
    "江苏": "jiangsu",
    "浙江": "zhejiang",
    "安徽": "anhui",
    "福建": "fujian",
    "江西": "jiangxi",
    "山东": "shandong",
    "河南": "henan",
    "湖北": "hubei",
    "湖南": "hunan",
    "广东": "guangdong",
    "广西": "guangxi",
    "海南": "hainan",
    "重庆": "chongqing",
    "四川": "sichuan",
    "贵州": "guizhou",
    "云南": "yunnan",
    "西藏": "xizang",
    "陕西": "shaanxi",
    "甘肃": "gansu",
    "青海": "qinghai",
    "宁夏": "ningxia",
    "新疆": "xinjiang",
}


def province_key(text: str | None) -> str | None:
    """中文省份名 → 省份键；已是键或无法识别时原样返回（``None`` 保持 ``None``）。"""
    if not text:
        return None
    text = text.strip()
    return _PROVINCE_KEY.get(text, text)


def _strip_markers(name: str) -> tuple[str, dict]:
    """剥离官方院校名里的后缀标注，返回 ``(净名, 属性)``。"""
    attributes: dict[str, Any] = {}
    clean = name
    for marker, (kind, value) in _NAME_SUFFIX.items():
        pattern = re.compile(rf"[（(]\s*{marker}\s*[)）]")
        if pattern.search(clean):
            clean = pattern.sub("", clean)
            if kind == "level":
                attributes.setdefault("level_tags", []).extend(
                    tag for tag in value if tag not in attributes.get("level_tags", [])
                )
            else:
                attributes[kind] = value
    return clean.strip(), attributes


def _build_colleges(rows: Iterable[SourceRow], *, catalog_meta: dict[str, dict]) -> list[dict]:
    """院校表：以**填报年**（2026）的名称为准，代码跨年稳定（实测 6 年共 1083 所代号不变）。

    填报年没有出现的院校（2026 年停招）用其最新可得年份的名称。

    两个必须处理的真实数据坑（M6 实测踩到）：
    1. **改名**：浙江每年都有一批"学院→大学"改名（湖州师范学院→湖州师范大学、
       浙江科技学院→浙江科技大学…），同一院校代号会同时出现新旧两个名字；
       ``colleges`` 主键是 ``{province}-{代号}``，按代号去重即可；
    2. **所在地只在合编 PDF 里有**：年度一段表（2026）没有"院校所在地"列，
       所以取"当年的名称"时不能顺手把所在地一起取空 —— 名称取当年行、
       所在地/城市**回填**该院校任意一年里最完整的那一行。
    """
    latest: dict[str, SourceRow] = {}
    located: dict[str, SourceRow] = {}
    for row in rows:
        current = latest.get(row.college_code)
        if current is None:
            latest[row.college_code] = row
        else:
            current_priority = (current.year == TARGET_YEAR, current.year)
            row_priority = (row.year == TARGET_YEAR, row.year)
            if row_priority > current_priority:
                latest[row.college_code] = row
        best = located.get(row.college_code)
        if row.college_province and row.college_city:
            if best is None or row.year > best.year:
                located[row.college_code] = row

    colleges: list[dict] = []
    for code in sorted(latest):
        row = latest[code]
        place = located.get(code, row)
        clean, attributes = _strip_markers(row.college_name)
        meta = catalog_meta.get(clean)
        level_tags = list(attributes.get("level_tags") or [])
        if meta:
            for tag in _LEVEL_TAGS.get(meta["tier"], []):
                if tag not in level_tags:
                    level_tags.append(tag)
        colleges.append(
            {
                "id": f"{PROVINCE}-{code}",
                "code": code,
                "name": clean,
                "province": province_key(place.college_province) or (meta or {}).get("province") or None,
                "city": place.college_city or (meta or {}).get("city") or None,
                "level_tags": json.dumps(level_tags, ensure_ascii=False),
                "college_type": (meta or {}).get("college_type"),
                "affiliation": attributes.get("affiliation"),
                "is_public": bool(attributes.get("is_public", True)),
                # 保研率 / 硕博点：官方投档表不发布 → 留空，不编造
                "postgrad_rate": None,
                "master_points": None,
                "doctor_points": None,
                "source_url": row.source_url,
                "is_synthetic": False,
            }
        )
    return colleges


def repo_root() -> Path:
    """仓库根（文件位于 ``backend/app/etl/loaders/``，向上 4 级）。

    与 ``app.config.REPO_ROOT`` 同解，但本模块属于 L1 ``etl``，**不得** import ``app.config``
    （那是 L4 层）；故在此独立解析并由测试守护（``tests/test_loaders_zhejiang.py``）。
    """
    return Path(__file__).resolve().parents[4]


def load_zhejiang(root: Path | str | None = None) -> RealZhejiangDataset:
    """装载浙江真实数据集（纯读取 + 组装，不碰数据库）。"""
    root = Path(root) if root is not None else repo_root()
    raw = root / "data" / "raw" / PROVINCE
    normalized = root / "data" / "normalized" / PROVINCE
    dataset = RealZhejiangDataset()

    # ---------- 读取全部来源 ----------
    rows: list[SourceRow] = []
    per_year: dict[int, list[SourceRow]] = defaultdict(list)
    for year in HISTORY_YEARS:
        path = normalized / f"zhejiang_parallel_compilation_{year}.csv"
        if not path.exists():
            dataset.gaps.append(f"缺 {year} 年合编 CSV（{path.name}），该年历史未导入")
            continue
        parsed = read_compilation_csv(path, year, source_url=_source(f"compilation={year}"))
        rows.extend(parsed)
        per_year[year].extend(parsed)
        dataset.notes.append(f"{year} 年合编 PDF 解析结果 {len(parsed)} 行（含选考科目要求）")

    for year in XLS_YEARS:
        paths = sorted((raw / str(year)).glob("*.xls"))
        if not paths:
            dataset.gaps.append(f"缺 {year} 年度一段表 .xls，该年专业代号与交叉校验不可用")
            continue
        parsed = read_annual_xls(paths[0], year, source_url=_source(f"annual={year}"))
        per_year[year].extend(parsed)
        if year != TARGET_YEAR:
            rows.extend(parsed)  # 仅用于交叉校验，不直接入库
        dataset.notes.append(f"{year} 年度一段表 {len(parsed)} 行（无选考要求，仅用于交叉校验）")

    if not per_year.get(TARGET_YEAR):
        raise FileNotFoundError(
            f"{TARGET_YEAR} 年投档单位缺失：请在 data/raw/{PROVINCE}/{TARGET_YEAR}/ 放置年度一段表 .xls"
        )

    # ---------- 专业链：以历史年（2023–2025）建立，2026 挂接其上 ----------
    historical_rows = [row for year in HISTORY_YEARS for row in per_year.get(year, [])]
    grouped: dict[tuple[str, str, str], list[SourceRow]] = defaultdict(list)
    for row in historical_rows:
        grouped[(row.college_code, row.base_key, row.name_key)].append(row)

    chains: list[MajorChain] = []
    by_college_base: dict[tuple[str, str], list[MajorChain]] = defaultdict(list)
    for (college_code, base_key, name_key) in sorted(grouped):
        bucket = by_college_base[(college_code, base_key)]
        ordinal = len(bucket) + 1
        slug = slug_of(base_key, salt=college_code) if ordinal == 1 else f"{slug_of(base_key, salt=college_code)}-{ordinal}"
        chain = MajorChain(
            college_code=college_code,
            base_key=base_key,
            slug=slug,
            ordinal=ordinal,
            exact_names={name_key},
            entries={},
        )
        entries, problems = _merge_duplicates(grouped[(college_code, base_key, name_key)])
        chain.entries.update(entries)
        dataset.notes.extend(problems)
        chains.append(chain)
        bucket.append(chain)

    # ---------- 2026（填报年）：挂接到既有链 ----------
    target_chain = _attach_target_year(
        per_year[TARGET_YEAR], chains, target_year=TARGET_YEAR, notes=dataset.notes
    )

    kept = {chain.slug for chain in target_chain.values()}
    dropped = [chain for chain in chains if chain.slug not in kept]
    dataset.gaps.append(
        f"{len(dropped)} 个专业链只存在于历史年、{TARGET_YEAR} 年已无招生（历史与计划行不导入）"
    )
    chains = [chain for chain in chains if chain.slug in kept]
    dataset.chains = chains

    # ---------- 院校 / 专业 / 投档单位 / 计划 / 历史 ----------
    catalog_meta = _college_meta_from_catalog()
    all_rows = [row for year in sorted(per_year) for row in per_year[year]]
    dataset.college_rows = _build_colleges(all_rows, catalog_meta=catalog_meta)

    major_seen: dict[str, dict] = {}
    unit_key_seen: set[str] = set()
    plan_seen: set[tuple[str, int]] = set()
    history_seen: set[tuple[str, int]] = set()
    quality_counter: Counter[str] = Counter()
    cross_check_hits = 0
    cross_check_checked = 0

    def unit_key_of_chain(chain: MajorChain) -> str:
        return f"{PROVINCE}-{chain.college_code}-NA-{chain.slug}"

    for chain in sorted(chains, key=lambda c: (c.college_code, c.slug)):
        target = chain.entries.get(TARGET_YEAR)
        assert target is not None  # kept 保证
        unit_key = unit_key_of_chain(chain)
        if unit_key in unit_key_seen:
            raise ValueError(f"unit_key 冲突：{unit_key}")
        unit_key_seen.add(unit_key)
        unit_id = f"{PROVINCE}-{TARGET_YEAR}-{chain.college_code}-NA-{chain.slug}"
        college_id = f"{PROVINCE}-{chain.college_code}"

        # 选考要求：优先当年；当年（年度 .xls）没有时用最近的历史年（同专业延续）
        requirement = None
        for year in [TARGET_YEAR, *sorted(chain.entries, reverse=True)]:
            row = chain.entries.get(year)
            if row is not None and row.subject_mode:
                requirement = row
                break
        if requirement is None:
            dataset.notes.append(
                f"{chain.college_code}/{target.major_name}: 无任何年份的选考科目要求，"
                "按'不限'入库并打缺数据标记"
            )
            subject_requirement = {"mode": "none", "subjects": []}
            req_note = "选考科目要求缺失（该专业未出现在 2023–2025 合编 PDF 中），按'不限'处理"
        else:
            subject_requirement = {
                "mode": requirement.subject_mode,
                "subjects": list(requirement.subject_subjects),
            }
            req_note = None

        major_id = f"{PROVINCE}-c{chain.college_code}-{chain.slug}"
        if major_id not in major_seen:
            # ★ 专业目录归属回填（ADR-018）：官方投档表**只发布专业名**，不发布
            #   门类/专业类。原先这里硬编码 None，导致 scoring 的"同一专业类 0.80 /
            #   同一门类 0.55 / 相关门类 0.30"三档对浙江真实数据**永不命中**，
            #   且 probability Step 0 的类比池塌缩成 discipline=None 一个桶。
            #   现改为调用 core 的确定性分类器，把专业名映射回教育部专业目录。
            #   定不出来的（0.2%）保持 None —— 宁可不答，不可编造。
            taxonomy = classify_major(
                target.major_name,
                level=(
                    LEVEL_ZHUANKE
                    if (target.duration or 0) == 3
                    else (LEVEL_BENKE if target.duration else None)
                ),
            )
            major_seen[major_id] = {
                "id": major_id,
                "code": chain.slug,
                "name": target.major_name,
                "category": taxonomy.category,
                "discipline": taxonomy.discipline,
                "degree": None,
                "duration": target.duration or (requirement.duration if requirement else None),
                "subject_eval_grade": None,
                "source_url": target.source_url,
                "is_synthetic": False,
            }

        remarks = ["真实数据（浙江省教育考试院公开投档表）"]
        if req_note:
            remarks.append(req_note)
        if target.data_quality == "MISSING_RANK":
            remarks.append("该项目本轮投档人数未满（位次栏为空）")
        dataset.admission_units.append(
            {
                "unit_id": unit_id,
                "unit_type": UNIT_TYPE,
                "province": PROVINCE,
                "year": TARGET_YEAR,
                "batch": BATCH,
                "college_id": college_id,
                "group_code": None,
                "group_name": None,
                "major_id": major_id,
                "major_name": target.major_name,
                "subject_requirement": json.dumps(subject_requirement, ensure_ascii=False),
                "subject_req_status": "PARSED",
                "plan_count": target.plan_count,
                "tuition": 0,  # 官方投档表不含学费 → 留 0，不编造
                "duration": target.duration or (requirement.duration if requirement else None),
                "campus": None,
                "remarks": "；".join(remarks),
                "is_synthetic": False,
                "source_url": target.source_url,
            }
        )

        for year, row in sorted(chain.entries.items()):
            key = (unit_key, year)
            if key not in plan_seen:
                plan_seen.add(key)
                dataset.admission_plans.append(
                    {
                        "unit_key": unit_key,
                        "year": year,
                        "plan_count": row.plan_count,
                        "is_synthetic": False,
                        "source_url": row.source_url,
                    }
                )
            if year == TARGET_YEAR:
                continue  # 填报年的计划数就是 unit 的 plan_count，不重复作为"历史"
            if row.min_rank is None:
                quality_counter["MISSING_RANK_SKIPPED"] += 1
                continue  # 位次为空 = 未满，按 DOMAIN_RULES §6.2 Step 1 不参与概率计算
            if (unit_key, year) in history_seen:
                continue
            history_seen.add((unit_key, year))
            quality_counter[row.data_quality] += 1
            verified = False
            if year == CROSS_CHECK_YEAR:
                xls_rank = _xls_rank(per_year.get(year, []), chain.college_code, row)
                if xls_rank is not None:
                    cross_check_checked += 1
                    if xls_rank == row.min_rank:
                        verified = True
                        cross_check_hits += 1
            dataset.admission_history.append(
                {
                    "unit_key": unit_key,
                    "province": PROVINCE,
                    "year": year,
                    "batch": BATCH,
                    "unit_type": UNIT_TYPE,
                    "college_id": college_id,
                    "group_code": None,
                    "major_id": major_id,
                    "min_score": row.min_score,
                    "min_rank": row.min_rank,
                    "avg_score": row.avg_score,
                    "avg_rank": None,
                    "plan_count": row.plan_count,
                    "admitted_count": row.plan_count,
                    "is_collected": row.data_quality == "COLLECTED",
                    "data_quality": row.data_quality,
                    "total_candidates": None,  # 由 province_year_stats 统一回填
                    "is_synthetic": False,
                    "source_url": row.source_url,
                    "verified": verified,
                }
            )

    dataset.major_rows = [major_seen[key] for key in sorted(major_seen)]

    # ---------- 一分一段表 + 年度元数据 ----------
    #
    # ★ 口径统一（M6 实测教训，见 SEGMENT1_CUMULATIVE 注释）：
    #   ``total_candidates`` 存**该年分数段表覆盖的最低分对应的累计人数**（官方原文口径，如实记录）；
    #   ``segment1_cumulative`` 存**一段线上的累计人数**（位次归一化的分母，历年同口径）。
    #   ``admission_history.total_candidates`` 必须等于后者（validate.py 强制），
    #   因为概率模型的跨年归一化用的就是它。
    official_tables = _years_with_official_table(root)
    years_needed = sorted({*HISTORY_YEARS, TARGET_YEAR})
    for year in years_needed:
        if year in official_tables:
            rows_year = read_score_segment_csv(official_tables[year], year)
            source_url = _source(f"score_segment={year}")
            is_synthetic = False
        else:
            if year not in SEGMENT1_CUMULATIVE:
                dataset.gaps.append(f"{year} 年既无官方分数段表也无官方一段上线人数，跳过")
                continue
            # 首选：用**当年真实投档记录的 (分数, 位次) 观测点**标定曲线（保序回归）
            observations = [
                (row.min_rank, row.min_score)
                for row in per_year.get(year, [])
                if row.min_rank and row.min_score
            ]
            rows_year = _empirical_score_table(year, observations, SEGMENT1_CUMULATIVE[year])
            if rows_year is None:
                rows_year = _gaussian_score_table(year, SEGMENT1_CUMULATIVE[year])
                dataset.gaps.append(
                    f"{year} 年无官方分数段表且当年观测点不足 {len(observations)} 条，"
                    "一分一段表退化为正态型模拟分布（is_synthetic=1）"
                )
            source_url = _source(
                f"score_segment={year}&estimated_from={len(observations)}observations"
                f"&anchored_at={SEGMENT_LINE[year][0]}"
            )
            is_synthetic = True
            dataset.gaps.append(
                f"{year} 年无官方分数段表：一分一段表由**当年 {len(observations)} 条官方投档记录**"
                f"（分数↔位次）保序回归标定，并在官方一段线 {SEGMENT_LINE[year][0]} 分处"
                f"按官方一段线上线人数 {SEGMENT1_CUMULATIVE[year]} 精确闭合；"
                f"来源：{SEGMENT1_SOURCE.get(year, '')}；整表标记 is_synthetic=1"
            )
        total = rows_year[-1][2] if rows_year else 0
        line_score = SEGMENT_LINE[year][0]
        line_row = next((row for row in rows_year if row[0] == line_score), None)
        if line_row is not None:
            segment1_cumulative = line_row[2]
        elif year in SEGMENT1_CUMULATIVE:
            segment1_cumulative = SEGMENT1_CUMULATIVE[year]
            dataset.gaps.append(
                f"{year} 官方分数段表没有一段线 {line_score} 分那一行，"
                f"一段线上线人数改用外部来源 {segment1_cumulative}"
            )
        else:  # pragma: no cover - 只有既无官方表又无外部来源时才会到这里
            segment1_cumulative = total
        for score, count, cumulative in rows_year:
            dataset.score_rank_table.append(
                {
                    "province": PROVINCE,
                    "year": year,
                    "track": TRACK,
                    "score": score,
                    "count_at_score": count,
                    "cumulative_rank": cumulative,
                    "source_url": source_url,
                    "is_synthetic": is_synthetic,
                }
            )
        dataset.province_year_stats.append(
            {
                "province": PROVINCE,
                "year": year,
                "track": TRACK,
                "total_candidates": total,
                "segment1_cumulative": segment1_cumulative,
                "segment1_line": line_score,
                "source_url": source_url,
                "is_synthetic": is_synthetic,
            }
        )

    # 历史行的归一化分母 = 该年分数段表覆盖的最低分累计人数（与库中位次同口径）
    official_totals = {row["year"]: row["total_candidates"] for row in dataset.province_year_stats}
    bases = {row["year"]: row["segment1_cumulative"] for row in dataset.province_year_stats}
    for row in dataset.admission_history:
        row["total_candidates"] = official_totals.get(row["year"])

    dataset.stats = {
        "target_year": TARGET_YEAR,
        "history_years": list(HISTORY_YEARS),
        "chains": len(chains),
        # 专业目录归属回填覆盖率（ADR-018）
        "major_taxonomy": dataset.taxonomy_counts(),
        "chains_with_3y_history": sum(
            1 for c in chains if sum(1 for y in HISTORY_YEARS if y in c.entries) == len(HISTORY_YEARS)
        ),
        "chains_without_history": sum(
            1 for c in chains if not any(y in c.entries for y in HISTORY_YEARS)
        ),
        "by_year": {
            year: {
                "rows": len(per_year.get(year, [])),
                "history_rows": sum(1 for h in dataset.admission_history if h["year"] == year),
            }
            for year in sorted(per_year)
        },
        "data_quality": dict(quality_counter),
        "cross_check": {
            "year": CROSS_CHECK_YEAR,
            "checked": cross_check_checked,
            "agreed": cross_check_hits,
        },
        "total_candidates": official_totals,
        "normalization_base": bases,
        "segment1_cumulative_source": {str(y): SEGMENT1_SOURCE.get(y, "官方分数段表原文") for y in years_needed},
        "segment_line": {year: SEGMENT_LINE[year][0] for year in years_needed if year in SEGMENT_LINE},
    }
    return dataset


def _xls_rank(rows: list[SourceRow], college_code: str, target: SourceRow) -> int | None:
    """从同年年度一段表里找同一 (院校代号, 专业名) 的位次（交叉校验用）。"""
    key = norm_name(target.major_name)
    for row in rows:
        if row.college_code != college_code or row.min_rank is None:
            continue
        if norm_name(row.major_name) == key:
            return row.min_rank
    return None


__all__ = [
    "BATCH",
    "CROSS_CHECK_YEAR",
    "HISTORY_YEARS",
    "PROVINCE",
    "RealZhejiangDataset",
    "TARGET_YEAR",
    "base_name",
    "load_zhejiang",
    "norm_name",
    "read_annual_xls",
    "read_compilation_csv",
    "read_score_segment_csv",
    "slug_of",
]
