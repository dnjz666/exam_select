"""专业分类器（四级）单测 —— ADR-018。

覆盖三件事：
1. **判定优先级**：目录精确名 → 专业类名 → 试验班 → 关键词 → 诚实兜底；
2. **规则库不变量**：门类/专业类的值域不能写错（曾实测把门类填进专业类字段）；
3. **覆盖率回归**：真实语料上的覆盖率不得回退（防止改规则时静默劣化）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.major_taxonomy_data import DIRECTION_KINDS
from app.core.major_taxonomy import (
    ALL_DISCIPLINES,
    ALL_DISCIPLINE_TO_CATEGORY,
    BENKE_CATEGORIES,
    DIRECTION_CATEGORY,
    DIRECTION_NARROWING,
    DISCIPLINE_KEYWORDS,
    DISCIPLINE_TO_CATEGORY,
    MAJOR_EXACT,
    MAJOR_EXACT_BY_LEVEL,
    TRAINING_CLASS_RULES,
    ZHUANKE_CATEGORIES,
    LEVEL_BENKE,
    LEVEL_ZHUANKE,
    TaxonomyStatus,
    category_of,
    classify_direction,
    classify_major,
    split_direction,
    taxonomy_from_stored,
)

# ---------------------------------------------------------------------------
# §1 规则库不变量 —— 数据错误比逻辑错误更隐蔽
# ---------------------------------------------------------------------------


class TestRuleInvariants:
    def test_benke_has_12_categories_and_93_disciplines(self):
        """教育部本科目录：12 门类 / 93 专业类。"""
        assert len(BENKE_CATEGORIES) == 12
        assert sum(len(v) for v in BENKE_CATEGORIES.values()) == 93

    def test_zhuanke_has_19_categories(self):
        """职业教育专业目录：19 大类。"""
        assert len(ZHUANKE_CATEGORIES) == 19

    def test_discipline_names_are_unique_across_categories(self):
        """专业类不得跨门类重名，否则 category_of 有歧义。"""
        seen: dict[str, str] = {}
        for category, disciplines in BENKE_CATEGORIES.items():
            for discipline in disciplines:
                assert discipline not in seen, f"{discipline} 同时属于 {seen.get(discipline)} 与 {category}"
                seen[discipline] = category

    def test_direction_narrowing_values_are_disciplines(self):
        """★ 收窄规则的值必须是**专业类**。

        实测踩过：``"卓越工程师": "工学"`` 把门类当专业类填，
        结果该专业的 ``category`` 变成 None（工学不是专业类，反查不到门类）。
        """
        for keyword, value in DIRECTION_NARROWING.items():
            assert value in ALL_DISCIPLINE_TO_CATEGORY, (
                f"direction_narrowing['{keyword}'] = '{value}' 不是合法专业类"
            )

    def test_direction_category_values_are_categories(self):
        for keyword, value in DIRECTION_CATEGORY.items():
            assert value in BENKE_CATEGORIES, (
                f"direction_category['{keyword}'] = '{value}' 不是合法门类"
            )

    def test_training_class_values_are_categories(self):
        for name, value in TRAINING_CLASS_RULES.items():
            assert value in BENKE_CATEGORIES, (
                f"training_class_rules['{name}'] = '{value}' 不是合法门类"
            )

    def test_major_exact_values_are_disciplines(self):
        """精确名映射的目标必须是合法专业类（本科 ∪ 专科，因为库里有专科专业名）。"""
        for name, value in MAJOR_EXACT.items():
            assert value in ALL_DISCIPLINE_TO_CATEGORY, (
                f"major_exact['{name}'] = '{value}' 不是合法专业类"
            )

    def test_discipline_keywords_keys_are_disciplines(self):
        for discipline in DISCIPLINE_KEYWORDS:
            assert discipline in ALL_DISCIPLINE_TO_CATEGORY, (
                f"discipline_keywords 的键 '{discipline}' 不是合法专业类"
            )

    def test_every_discipline_has_a_category(self):
        for discipline in ALL_DISCIPLINES:
            assert category_of(discipline) is not None
        # 本科专业类必须映射到本科 12 门类
        for discipline in DISCIPLINE_TO_CATEGORY:
            assert category_of(discipline) in BENKE_CATEGORIES


# ---------------------------------------------------------------------------
# §2 招生方向解析（L4）
# ---------------------------------------------------------------------------


class TestSplitDirection:
    @pytest.mark.parametrize(
        ("raw", "base", "direction"),
        [
            ("计算机类", "计算机类", None),
            ("计算机类(中外合作办学)", "计算机类", "中外合作办学"),
            ("计算机科学与技术（基础拔尖基地班）", "计算机科学与技术", "基础拔尖基地班"),
            ("工商管理(工管与软工双学士学位)", "工商管理", "工管与软工双学士学位"),
            ("工科试验班(智慧城市与建筑工程)", "工科试验班", "智慧城市与建筑工程"),
            ("", "", None),
        ],
    )
    def test_split(self, raw, base, direction):
        assert split_direction(raw) == (base, direction)

    def test_multiple_parentheses_joined(self):
        base, direction = split_direction("专业(方向一)(方向二)")
        assert base == "专业"
        assert direction == "方向一 方向二"


class TestClassifyDirection:
    @pytest.mark.parametrize(
        ("direction", "expected"),
        [
            (None, None),
            ("中外合作办学", "SINO_FOREIGN"),
            ("卓越工程师", "EXCELLENCE"),
            ("基础拔尖基地班", "TOP_TALENT"),
            ("工管与软工双学士学位", "DOUBLE_DEGREE"),
            ("师范", "NORMAL"),
            ("定向培养", "ORIENTED"),
            ("杭州校区", "CAMPUS"),
            ("某个没见过的方向", "MAJOR_DIRECTION"),
        ],
    )
    def test_kinds(self, direction, expected):
        assert classify_direction(direction) == expected


# ---------------------------------------------------------------------------
# §3 判定优先级（L1/L2/L3）
# ---------------------------------------------------------------------------


class TestClassifyPriority:
    def test_catalog_exact_wins(self):
        t = classify_major("计算机科学与技术", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.CATALOG_EXACT
        assert (t.category, t.discipline) == ("工学", "计算机类")

    def test_direction_is_stripped_before_matching(self):
        t = classify_major("计算机科学与技术(基础拔尖基地班)", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.CATALOG_EXACT
        assert t.discipline == "计算机类"
        assert t.direction == "基础拔尖基地班"
        assert t.direction_kind == "TOP_TALENT"

    def test_discipline_name_matches_itself(self):
        t = classify_major("计算机类", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.DISCIPLINE_NAME
        assert (t.category, t.discipline) == ("工学", "计算机类")

    def test_training_class_without_direction_gives_category_only(self):
        t = classify_major("社会科学试验班", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.TRAINING_CLASS
        assert t.category == "管理学"
        assert t.discipline is None
        assert t.is_classified is True
        assert t.has_discipline is False

    def test_training_class_narrowed_by_direction(self):
        t = classify_major("工科试验班(计算机)", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.DIRECTION_NARROWED
        assert t.discipline == "计算机类"
        assert t.category == "工学"

    def test_training_class_narrowed_only_to_category(self):
        """方向只能定到门类时，门类要有值（实测踩过 None）。"""
        t = classify_major("工科试验班(竺可桢学院卓越工程师班)", level=LEVEL_BENKE)
        assert t.category == "工学"
        assert t.discipline is None

    def test_unknown_training_class_is_honest(self):
        t = classify_major("某某学院实验班", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.TRAINING_CLASS
        assert t.is_classified is False

    def test_keyword_rule(self):
        t = classify_major("智能建造", level=LEVEL_BENKE)
        assert t.discipline == "土木类"
        assert t.category == "工学"

    def test_keyword_longest_match_wins(self):
        """长关键词优先：'机械电子工程' 不应被 '机械' 抢走。"""
        t = classify_major("机械电子工程", level=LEVEL_BENKE)
        assert t.discipline == "机械类"

    def test_unclassified_never_guesses(self):
        """★ 宁可不答，不可编造。"""
        t = classify_major("某个不存在的专业名XYZ", level=LEVEL_BENKE)
        assert t.status is TaxonomyStatus.UNCLASSIFIED
        assert t.category is None and t.discipline is None
        assert t.is_classified is False

    def test_empty_name(self):
        t = classify_major("")
        assert t.status is TaxonomyStatus.UNCLASSIFIED

    def test_zhuanke_level_is_recorded_but_uses_same_disciplines(self):
        t = classify_major("大数据技术", level=LEVEL_ZHUANKE)
        assert t.level == LEVEL_ZHUANKE
        assert t.discipline == "计算机类"

    def test_source_url_present(self):
        t = classify_major("计算机类")
        assert t.source_url.startswith("https://")


# ---------------------------------------------------------------------------
# §4 taxonomy_from_stored —— 库中已回填的优先
# ---------------------------------------------------------------------------


class TestTaxonomyFromStored:
    def test_stored_values_win(self):
        t = taxonomy_from_stored("计算机类", "工学", "计算机类")
        assert (t.category, t.discipline) == ("工学", "计算机类")

    def test_falls_back_to_classifier_when_empty(self):
        t = taxonomy_from_stored("计算机类", None, None)
        assert t.discipline == "计算机类"
        assert t.status is TaxonomyStatus.DISCIPLINE_NAME

    def test_category_derived_from_discipline_when_missing(self):
        t = taxonomy_from_stored("计算机类", None, "计算机类")
        assert t.category == "工学"

    def test_direction_still_parsed_from_name(self):
        t = taxonomy_from_stored("计算机类(中外合作办学)", "工学", "计算机类")
        assert t.direction == "中外合作办学"
        assert t.direction_kind == "SINO_FOREIGN"


# ---------------------------------------------------------------------------
# §5 真实语料覆盖率回归（★ 防止改规则时静默劣化）
# ---------------------------------------------------------------------------

#: 浙江 2026 真实投档表中出现过的代表性专业名（含最难归类的几类）
ZHEJIANG_SAMPLE = [
    # 目录精确名
    "计算机科学与技术", "软件工程", "临床医学", "法学", "汉语言文学", "会计学",
    "英语", "数学与应用数学", "土木工程", "机械设计制造及其自动化",
    # 大类招生
    "计算机类", "电子信息类", "机械类", "工商管理类", "公共管理类",
    # 试验班
    "工科试验班", "理科试验班", "社会科学试验班", "人文科学试验班",
    "工科试验班(计算机)", "工科试验班(电子信息)",
    # 带方向
    "计算机科学与技术(基础拔尖基地班)", "数据科学与大数据技术(中外合作办学)",
    "机械工程(卓越工程师)", "工商管理(工管与软工双学士学位)", "小学教育(师范)",
    # 专科
    "大数据技术", "人工智能技术应用", "护理", "学前教育", "电子商务",
    "机电一体化技术", "建筑工程技术", "酒店管理",
    # 浙工大实际专业
    "健行学院实验班(智能科学)", "健行学院实验班(分子化学工程)", "机器人工程",
    "空间信息与数字技术", "食品科学与工程类", "药学类(“2011计划”创新实验区)",
    "建筑学", "城乡规划", "安全工程", "能源与环境系统工程", "应用心理学",
]


class TestCoverageRegression:
    def test_sample_is_fully_classified_at_category_level(self):
        """代表性样本必须全部定到门类（否则说明规则库退化）。"""
        failures = []
        for name in ZHEJIANG_SAMPLE:
            t = classify_major(name)
            if not t.is_classified:
                failures.append((name, t.status.value))
        assert not failures, f"以下专业名未能定到门类：{failures}"

    def test_sample_discipline_coverage_at_least_90_percent(self):
        classified = [classify_major(n) for n in ZHEJIANG_SAMPLE]
        with_disc = sum(1 for t in classified if t.has_discipline)
        ratio = with_disc / len(classified)
        assert ratio >= 0.90, f"专业类覆盖率 {ratio:.1%} < 90%"

    def test_zjut_majors_all_resolve(self):
        """浙工大 2026 全部 50 个专业都应能定到门类。"""
        zjut = [
            "人工智能", "信息与计算科学(信计与自动化双学士学位)",
            "健行学院实验班(人文社科)", "健行学院实验班(分子化学工程)",
            "健行学院实验班(智慧能源创新)", "健行学院实验班(智能生物制造)",
            "健行学院实验班(智能科学)", "健行学院实验班(理工)", "公共管理类",
            "化学工程与工艺(卓越工程师)", "化工与制药类(化学工程类)",
            "国际经济与贸易", "城乡规划", "安全工程", "工业设计",
            "工商管理(工管与软工双学士学位)", "工商管理类", "应用心理学",
            "应用物理学(基础拔尖基地班)", "建筑学", "数字媒体技术(中外合作办学)",
            "数学类", "数据科学与大数据技术", "数据科学与大数据技术(中外合作办学)",
            "新能源科学与工程", "新闻传播学类", "智能建造", "机器人工程",
            "机械工程(卓越工程师)", "机械工程(机械与工管双学士学位)", "机械类",
            "材料类", "汉语言文学", "法学", "物理学类(物理与光电信息类)",
            "环境科学与工程类", "生物工程类", "电子信息类", "电气类",
            "空间信息与数字技术", "管理科学与工程类", "能源与环境系统工程",
            "英语", "药学(药学与计算机双学士学位)", "药学类(“2011计划”创新实验区)",
            "计算机科学与技术(基础拔尖基地班)", "计算机类", "软件工程(中外合作办学)",
            "金融学", "食品科学与工程类",
        ]
        assert len(zjut) == 50
        failures = [(n, classify_major(n).status.value) for n in zjut if not classify_major(n).is_classified]
        assert not failures, f"浙工大专业未归类：{failures}"


# ---------------------------------------------------------------------------
# §6 文档与数据同步（★ 防止"改了规则忘了同步文档附录"）
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DOC = REPO_ROOT / "docs" / "MAJOR_TAXONOMY.md"
TAXONOMY_JSON = REPO_ROOT / "data" / "taxonomy" / "major_taxonomy.json"


class TestDocSync:
    def test_doc_appendix_lists_every_benke_discipline(self):
        """文档附录 A 必须列出**全部** 93 个本科专业类（人可读的"归属哪个门"清单）。"""
        text = TAXONOMY_DOC.read_text(encoding="utf-8")
        begin = "<!-- BEGIN GENERATED: benke-discipline-table -->"
        end = "<!-- END GENERATED: benke-discipline-table -->"
        assert begin in text and end in text, "附录 A 的生成标记丢失"
        block = text.split(begin, 1)[1].split(end, 1)[0]

        missing = [
            d
            for disciplines in BENKE_CATEGORIES.values()
            for d in disciplines
            if f"`{d}`" not in block
        ]
        assert not missing, f"附录 A 缺少这些专业类：{missing}"

    def test_doc_appendix_lists_every_benke_category(self):
        text = TAXONOMY_DOC.read_text(encoding="utf-8")
        block = text.split("<!-- BEGIN GENERATED: benke-discipline-table -->", 1)[1]
        block = block.split("<!-- END GENERATED: benke-discipline-table -->", 1)[0]
        missing = [c for c in BENKE_CATEGORIES if f"**{c}**" not in block]
        assert not missing, f"附录 A 缺少这些门类：{missing}"

    def test_doc_appendix_lists_every_zhuanke_category(self):
        text = TAXONOMY_DOC.read_text(encoding="utf-8")
        block = text.split("<!-- BEGIN GENERATED: zhuanke-category-table -->", 1)[1]
        block = block.split("<!-- END GENERATED: zhuanke-category-table -->", 1)[0]
        missing = [c for c in ZHUANKE_CATEGORIES if f"**{c}**" not in block]
        assert not missing, f"附录 B 缺少这些专科大类：{missing}"

    def test_json_editing_source_agrees_with_runtime_module(self):
        """JSON 编辑源与运行时 Python 模块必须一致（否则谁改了哪份都说不清）。"""
        import json

        data = json.loads(TAXONOMY_JSON.read_text(encoding="utf-8"))
        assert data["benke_categories"] == BENKE_CATEGORIES
        assert data["zhuanke_categories"] == ZHUANKE_CATEGORIES
        assert data["major_exact"] == MAJOR_EXACT
        assert data["discipline_keywords"] == DISCIPLINE_KEYWORDS
        assert data["training_class_rules"] == TRAINING_CLASS_RULES
        assert data["direction_narrowing"] == DIRECTION_NARROWING
        assert data["direction_category"] == DIRECTION_CATEGORY
        assert data["major_exact_by_level"] == MAJOR_EXACT_BY_LEVEL


class TestNoDuplicateJsonKeys:
    """★ JSON 重复键会**静默覆盖**（取最后一个）。

    实测踩到：``major_exact`` 积了 554 个重复键，其中 7 个值冲突，
    导致 `交通管理`/`人力资源管理`/`智慧海洋技术`/`社区管理与服务` 四个名字
    被静默归错类（影响 110 行）。这组用例把该缺陷钉死。
    """

    @staticmethod
    def _find_duplicates(text: str) -> dict[str, list[object]]:
        import json
        from collections import defaultdict

        found: dict[str, list[object]] = defaultdict(list)

        def hook(pairs):
            seen: dict[str, object] = {}
            for key, value in pairs:
                if key in seen:
                    found[key].append(seen[key])
                    found[key].append(value)
                seen[key] = value
            return seen

        json.loads(text, object_pairs_hook=hook)
        return found

    def test_json_has_no_duplicate_keys(self):
        dups = self._find_duplicates(TAXONOMY_JSON.read_text(encoding="utf-8"))
        assert not dups, f"规则库 JSON 出现重复键（后者会静默覆盖前者）：{dict(dups)}"

    def test_duplicate_detector_is_object_scoped_not_flat(self):
        """守卫必须**逐对象**检测：9 个方向类型各自的 label/keywords 不是重复键。

        早期版本的检测脚本做了全文扁平扫描，把嵌套同名键误报成 3 个冲突。
        """
        text = TAXONOMY_JSON.read_text(encoding="utf-8")
        assert not self._find_duplicates(text)
        # direction_kinds 下每个类型都有自己的 label / keywords / notes
        assert len({spec["label"] for spec in DIRECTION_KINDS.values()}) == len(
            DIRECTION_KINDS
        )

    def test_detector_actually_catches_duplicates(self):
        """反向验证：检测器对真正的重复键必须报警（防止守卫本身失效）。"""
        bad = '{"a": {"k": 1, "k": 2}}'
        assert "k" in self._find_duplicates(bad)


class TestConflictResolutions:
    """7 个曾值冲突的键，逐个钉住最终判定（依据见 scripts/dedupe_major_taxonomy.py）。"""

    @pytest.mark.parametrize(
        ("name", "expected_discipline"),
        [
            ("交通管理", "公共管理类"),      # 本科 120407T；公安技术类里叫「交通管理工程」
            ("人力资源管理", "工商管理类"),    # 本科 120206（专科另由 by_level 分流）
            ("动漫制作技术", "计算机类"),      # 专科 510215，前缀 51=电子与信息大类
            ("建筑消防技术", "建筑类"),
            ("智慧海洋技术", "海洋工程类"),
            ("水生态修复技术", "环境科学与工程类"),
            ("社区管理与服务", "公共管理类"),
        ],
    )
    def test_conflict_key_resolves_to_expected(self, name, expected_discipline):
        assert MAJOR_EXACT[name] == expected_discipline

    def test_traffic_management_keyword_ambiguity_removed(self):
        """`交通管理` 原先同时出现在交通运输类与公共管理类的关键词表里 → 已从前者移除。"""
        assert "交通管理" not in DISCIPLINE_KEYWORDS["交通运输类"]
        assert "交通管理" not in DISCIPLINE_KEYWORDS.get("公安学类", [])
        assert "交通管理" in DISCIPLINE_KEYWORDS["公共管理类"]

    def test_water_ecology_keyword_added(self):
        """`水生态修复技术` 原先关键词层无命中 → 已补关键词，让两层一致。"""
        assert "水生态修复" in DISCIPLINE_KEYWORDS["环境科学与工程类"]


class TestLevelAwareClassification:
    """★ 真实的两级分裂：同名专业在本科/专科属不同专业类。"""

    def test_human_resources_benke_vs_zhuanke(self):
        benke = classify_major("人力资源管理", level=LEVEL_BENKE)
        zhuanke = classify_major("人力资源管理", level=LEVEL_ZHUANKE)
        assert benke.discipline == "工商管理类"
        assert zhuanke.discipline == "公共管理类"
        assert benke.status is TaxonomyStatus.CATALOG_EXACT
        assert zhuanke.status is TaxonomyStatus.CATALOG_EXACT
        assert "分流" in zhuanke.evidence

    def test_unknown_level_falls_back_to_default_with_note(self):
        """学制未知时不猜 —— 用默认（本科）口径，并在 evidence 里注明存在分流。"""
        unknown = classify_major("人力资源管理")
        assert unknown.discipline == "工商管理类"
        assert "不同归属" in unknown.evidence

    def test_direction_suffix_still_works_with_level_split(self):
        t = classify_major("人力资源管理(中外合作办学)", level=LEVEL_ZHUANKE)
        assert t.discipline == "公共管理类"
        assert t.direction == "中外合作办学"
        assert t.direction_kind == "SINO_FOREIGN"

    def test_by_level_keys_must_exist_in_major_exact(self):
        """by_level 的键必须在 major_exact 里有对应条目（否则是永远命中不了的死规则）。"""
        for name in MAJOR_EXACT_BY_LEVEL:
            assert name in MAJOR_EXACT, f"major_exact_by_level['{name}'] 是死规则"

    def test_by_level_values_are_disciplines(self):
        for name, levels in MAJOR_EXACT_BY_LEVEL.items():
            for level, discipline in levels.items():
                assert level in {"BENKE", "ZHUANKE"}, f"{name} 的学制键 {level} 非法"
                assert discipline in ALL_DISCIPLINE_TO_CATEGORY, (
                    f"major_exact_by_level['{name}']['{level}'] = {discipline} 不是合法专业类"
                )
