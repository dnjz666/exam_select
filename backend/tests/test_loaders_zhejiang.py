"""真实数据适配器测试（M6 / ADR-015）。

覆盖四件事，每件都对着"错了会导致真实填报事故"：
1. **解析**：官方 .xls / 合编 CSV / 官方分数段表 PDF-解析产物能被正确读出（列、行数、边界）；
2. **跨年对齐**：`unit_key` 用「院校代号 + 专业名」而不是浙江年年重排的「专业代号」，
   且历年位次确实挂在同一把 key 上；
3. **口径**：归一化分母与历史行、分数段表三者自洽（这是位次法不失真的前提）；
4. **纪律**：平台/来源标记正确（官方分数段表 `is_synthetic=0`，标定表 `is_synthetic=1`）、
   幂等（同输入同 digest）、不留孤儿引用。

这些测试只读 ``data/`` 下的真实文件（与后端测试同一前置条件：仓库里有 M6 采集到的数据）。
"""

from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

import pytest

from app.etl.loaders.zhejiang import (
    BATCH,
    CROSS_CHECK_YEAR,
    HISTORY_YEARS,
    PROVINCE,
    TARGET_YEAR,
    base_name,
    load_zhejiang,
    norm_name,
    province_key,
    read_annual_xls,
    read_compilation_csv,
    read_score_segment_csv,
    repo_root,
    slug_of,
)

ROOT = repo_root()
RAW = ROOT / "data" / "raw" / PROVINCE
NORMALIZED = ROOT / "data" / "normalized" / PROVINCE


@pytest.fixture(scope="module")
def dataset():
    return load_zhejiang()


# ---------------------------------------------------------------------------
# 1) 文本归一与专业名匹配
# ---------------------------------------------------------------------------
def test_norm_name_unifies_brackets_and_spaces() -> None:
    assert norm_name("工科试验班（信息）") == norm_name("工科试验班(信息)")
    assert norm_name("药学 ( 药学与计算机双学士学位)") == "药学(药学与计算机双学士学位)"
    assert slug_of("工科试验班") == slug_of("工科试验班")
    assert slug_of("工科试验班") != slug_of("工科试验班", salt="0001")


def test_base_name_strips_nested_brackets() -> None:
    assert base_name("机械工程(机械与工管双学士学位)") == "机械工程"
    assert base_name("计算机类（中外合作办学）") == "计算机类"
    # 嵌套：内层括号一并剥离，不能只剥一层
    assert base_name("大类的(子类(方向))") == "大类的"
    assert base_name("不限") == "不限"


def test_province_key_maps_chinese_names_to_rule_keys() -> None:
    """官方投档表的"院校所在地"是中文，规则包键是英文 —— 必须归一，否则院校被算两所。"""
    assert province_key("浙江") == "zhejiang"
    assert province_key("北京") == "beijing"
    assert province_key("zhejiang") == "zhejiang"
    assert province_key(None) is None


# ---------------------------------------------------------------------------
# 2) 源文件解析
# ---------------------------------------------------------------------------
def test_read_annual_xls_rejects_missing_rank_as_missing_rank(tmp_path: Path) -> None:
    """官方表尾注释：位次栏为空 = 该专业本轮投档人数未满 → data_quality=MISSING_RANK。

    这条口径直接决定"未满"记录不进概率模型（DOMAIN_RULES §6.2 Step 1）。
    """
    paths = sorted((RAW / str(CROSS_CHECK_YEAR)).glob("*.xls"))
    assert paths, "缺少 2024 年度一段表 .xls"
    rows = read_annual_xls(paths[0], CROSS_CHECK_YEAR, source_url="test://xls")
    assert len(rows) > 15_000
    assert all(row.college_code and row.major_name for row in rows)
    assert all(row.subject_mode == "" for row in rows), "年度一段表不含选考要求，不得编造"
    missing = [row for row in rows if row.data_quality == "MISSING_RANK"]
    assert missing, "2024 年应有'位次为空=未满'的行"
    assert all(row.min_rank is None for row in missing)
    assert all(row.min_rank for row in rows if row.data_quality == "OK")


def test_read_compilation_csv_carries_subject_requirement() -> None:
    path = NORMALIZED / f"zhejiang_parallel_compilation_{HISTORY_YEARS[-1]}.csv"
    rows = read_compilation_csv(path, HISTORY_YEARS[-1], source_url="test://compilation")
    assert len(rows) > 20_000
    modes = collections.Counter(row.subject_mode for row in rows)
    assert set(modes) <= {"all_of", "any_of", "none", ""}
    # 2024/2025 浙江把绝大多数理工专业改成「物理&化学」（all_of），2023 还有「物理/化学」（any_of）
    # —— 这条断言同时锁住"斜杠=任选一门、& =均须选考"的官方口径不会被改反
    assert modes["none"] > 0 and modes["all_of"] > 0
    any_2023 = read_compilation_csv(
        NORMALIZED / f"zhejiang_parallel_compilation_{HISTORY_YEARS[0]}.csv",
        HISTORY_YEARS[0],
        source_url="test://compilation",
    )
    assert collections.Counter(row.subject_mode for row in any_2023)["any_of"] > 0
    # 位次与分数要么都有、要么明确标成未满（不允许"有位次无分数"这种半条记录）
    for row in rows:
        assert (row.min_rank is None) or (row.min_score is not None)
        if row.min_rank is None:
            assert row.data_quality == "MISSING_RANK"

def test_read_official_score_segment_matches_published_headline() -> None:
    """官方 2026 分数段表：一段线 494 → 184,816；表底 266 分 → 292,753（原文数字）。"""
    path = NORMALIZED / "zhejiang_score_segment_2026.csv"
    rows = read_score_segment_csv(path, TARGET_YEAR)
    by_score = {score: (count, cumulative) for score, count, cumulative in rows}
    assert by_score[494][1] == 184_816
    assert by_score[490][1] == 189_111
    assert rows[-1][0] == 266 and rows[-1][2] == 292_753
    # 累计必须自洽且单调
    previous = 0
    for score, count, cumulative in rows:
        assert cumulative == previous + count
        assert count > 0
        previous = cumulative


# ---------------------------------------------------------------------------
# 3) 数据集整体：口径、对齐、引用完整性
# ---------------------------------------------------------------------------
def test_counts_and_target_year(dataset) -> None:
    counts = dataset.counts()
    assert counts["admission_units"] > 15_000
    assert counts["admission_history"] > 30_000
    assert counts["majors"] == counts["admission_units"], "一条专业链=一个当年投档单位"
    assert dataset.stats["target_year"] == TARGET_YEAR
    assert tuple(dataset.stats["history_years"]) == HISTORY_YEARS
    # 填报年不得进入历史（否则回测会数据泄漏）
    assert all(row["year"] != TARGET_YEAR for row in dataset.admission_history)


def test_unit_key_is_stable_across_years(dataset) -> None:
    """★ 核心：跨年对齐靠「院校代号 + 专业名」，不是年年重排的专业代号。

    浙江大学「工科试验班」2023 与 2025 的专业代号不同，但必须挂到同一把 unit_key 上。
    """
    by_key = collections.defaultdict(dict)
    for row in dataset.admission_history:
        by_key[row["unit_key"]][row["year"]] = row
    multi_year = [key for key, years in by_key.items() if len(years) >= 3]
    assert len(multi_year) > 5_000, "三年都有记录的链数量过少，跨年对齐可能失效"
    # 同一把 key 的历年行必须同院校、同专业名（专业名可含方向括号差异）
    chains = {chain.slug: chain for chain in dataset.chains}
    for key in multi_year[:200]:
        # unit_key = {province}-{college_code}-NA-{slug}，slug 自身可能含 "-"（同名多链）
        slug = key.split("-", 3)[3]
        chain = chains.get(slug)
        assert chain is not None, key
        years = by_key[key]
        assert set(years) <= set(HISTORY_YEARS) | {TARGET_YEAR}
        for row in years.values():
            assert row["college_id"] == f"{PROVINCE}-{chain.college_code}"


def test_normalization_base_is_consistent_everywhere(dataset) -> None:
    """归一化分母必须三处一致：province_year_stats、admission_history、分数段表闭合。

    任何一处不一致都会让"同一含金量的位次"在跨年比较时被凭空放大/缩小（ADR-015）。
    """
    stats = {row["year"]: row for row in dataset.province_year_stats}
    table_totals = collections.defaultdict(int)
    for row in dataset.score_rank_table:
        table_totals[row["year"]] = max(table_totals[row["year"]], row["cumulative_rank"])
    for year, row in stats.items():
        assert table_totals[year] == row["total_candidates"], year
        assert row["segment1_cumulative"] <= row["total_candidates"], year
    for hist in dataset.admission_history:
        assert hist["total_candidates"] == stats[hist["year"]]["total_candidates"]


def test_score_table_is_monotone_with_unique_scores(dataset) -> None:
    by_year = collections.defaultdict(list)
    for row in dataset.score_rank_table:
        by_year[row["year"]].append(row)
    for year, rows in by_year.items():
        scores = [row["score"] for row in rows]
        assert len(scores) == len(set(scores)), f"{year} 分数重复（UNIQUE 约束会拦）"
        rows.sort(key=lambda r: -r["score"])
        previous = 0
        for row in rows:
            assert row["count_at_score"] > 0
            assert row["cumulative_rank"] == previous + row["count_at_score"]
            previous = row["cumulative_rank"]


def test_official_table_is_not_marked_synthetic(dataset) -> None:
    """2026 有官方分数段表原文 → 必须 is_synthetic=0；2023–2025 是标定估计 → =1。"""
    official = [row for row in dataset.score_rank_table if row["year"] == TARGET_YEAR]
    modeled = [row for row in dataset.score_rank_table if row["year"] in HISTORY_YEARS]
    assert official and all(row["is_synthetic"] is False for row in official)
    assert modeled and all(row["is_synthetic"] is True for row in modeled)
    real_history = [row for row in dataset.admission_history]
    assert all(row["is_synthetic"] is False for row in real_history), "投档数据全部来自官方原文"


def test_rank_score_consistency_of_modeled_tables(dataset) -> None:
    """标定表与官方记录必须基本自洽（自洽是构造保证，这里防止日后改坏）。"""
    lookup = collections.defaultdict(list)
    for row in dataset.score_rank_table:
        lookup[row["year"]].append((row["score"], row["cumulative_rank"]))
    for rows in lookup.values():
        rows.sort(key=lambda item: -item[0])

    def score_for_rank(rows: list[tuple[int, int]], rank: int) -> int:
        if rank >= rows[-1][1]:
            return rows[-1][0]
        for index in range(1, len(rows)):
            low, high = rows[index - 1][1], rows[index][1]
            if high >= rank:
                if high == low:
                    return rows[index][0]
                ratio = (rank - low) / (high - low)
                return int(round(rows[index - 1][0] + ratio * (rows[index][0] - rows[index - 1][0])))
        return rows[-1][0]

    checked = 0
    inconsistent = 0
    for hist in dataset.admission_history:
        if not hist["min_rank"] or not hist["min_score"]:
            continue
        checked += 1
        if abs(score_for_rank(lookup[hist["year"]], hist["min_rank"]) - hist["min_score"]) > 2:
            inconsistent += 1
    assert checked > 30_000
    # 标定表是"录取口径"的近似，允许少量插值残差；超过 5% 说明表被改坏了
    assert inconsistent / checked < 0.05, f"{inconsistent}/{checked} 反查分数不自洽"


def test_every_unit_is_complete_and_referenced(dataset) -> None:
    college_ids = {row["id"] for row in dataset.college_rows}
    major_ids = {row["id"] for row in dataset.major_rows}
    unit_keys: set[str] = set()
    for unit in dataset.admission_units:
        assert unit["unit_type"] == "MAJOR_COLLEGE"
        assert unit["batch"] == BATCH
        assert unit["province"] == PROVINCE
        assert unit["year"] == TARGET_YEAR
        assert unit["plan_count"] > 0
        assert unit["subject_req_status"] == "PARSED"
        requirement = json.loads(unit["subject_requirement"])
        assert requirement["mode"] in {"all_of", "any_of", "none"}
        assert unit["college_id"] in college_ids
        assert unit["major_id"] in major_ids
        unit_keys.add(unit["unit_id"][: len(PROVINCE)] + unit["unit_id"][len(PROVINCE) + 5 :])
    assert len(unit_keys) == len(dataset.admission_units), "unit_key 必须唯一"
    for row in dataset.admission_plans:
        assert row["plan_count"] > 0
    # 不断言 plan/history 的 unit_key 全集（脚本层还会剔掉孤儿），但要保证当年单位都有计划行
    plan_keys = {(row["unit_key"], row["year"]) for row in dataset.admission_plans}
    for unit in dataset.admission_units[:500]:
        key = unit["unit_id"][: len(PROVINCE)] + unit["unit_id"][len(PROVINCE) + 5 :]
        assert (key, TARGET_YEAR) in plan_keys


def test_history_rows_have_source_url(dataset) -> None:
    """来源纪律：任何数字都必须能追溯到具体官方文件（AGENTS.md §5.2 / §7）。"""
    for row in dataset.admission_history:
        assert row["source_url"].startswith("real://")
        # 历史行来自合编 PDF（含选考要求）或年度一段表（交叉校验年）
        assert "compilation=" in row["source_url"] or "annual=" in row["source_url"]
    for row in dataset.admission_units:
        assert row["source_url"].startswith("real://")
        assert "annual=2026" in row["source_url"]


def test_cross_check_against_independent_official_source(dataset) -> None:
    """2024 年同时有合编 PDF 与年度一段表两个独立官方来源 → 交叉校验命中率应接近 100%。"""
    cross = dataset.stats["cross_check"]
    assert cross["year"] == CROSS_CHECK_YEAR
    assert cross["checked"] > 10_000
    assert cross["agreed"] / cross["checked"] > 0.99


def test_gaps_are_disclosed_not_filled_with_invented_numbers(dataset) -> None:
    """缺口必须**如实披露**：无官方分数段表的年份要标出来，不许悄悄用模拟值充数。"""
    joined = "\n".join(dataset.gaps)
    assert "无官方分数段表" in joined
    assert "2026" not in joined or "2026 年既无官方分数段表" not in joined


def test_loader_is_deterministic(dataset) -> None:
    """同一份源文件重复装载必须逐字节一致（幂等的另一半：seed 脚本负责先删后写）。"""
    assert load_zhejiang(ROOT).digest() == dataset.digest()


def test_manifest_registers_every_raw_file() -> None:
    """每个采集到的原始文件都要在 manifest 里登记来源 URL 与 sha256。"""
    manifest = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    files = {record["file"] for entry in manifest.values() for record in entry.get("files", [])}
    assert any("score_segment" in name or "成绩分数段表" in name for name in files)
    for name in files:
        assert (ROOT / name).exists(), name
    for entry in manifest.values():
        for record in entry.get("files", []):
            assert record.get("sha256") and len(record["sha256"]) == 64


def test_normalized_csv_encodings_are_excel_friendly() -> None:
    """规范化 CSV 必须是 UTF-8 BOM（交付包要求 Excel 可直接打开）。"""
    for path in sorted(NORMALIZED.glob("*.csv")):
        with path.open("rb") as handle:
            assert handle.read(3) == b"\xef\xbb\xbf", path.name
