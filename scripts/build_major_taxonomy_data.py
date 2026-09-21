"""把 ``data/taxonomy/major_taxonomy.json`` 转成 core 内的纯 Python 数据模块。

为什么分两步（JSON 编辑源 → Python 模块）：
* ``core/`` 禁止文件 IO（ADR-003），所以运行时只能读模块常量；
* 但 1,100+ 条映射用 JSON 维护更易读易审，因此保留 JSON 作为**编辑源**。

本脚本同时做**不变量校验**（值域、重名、唯一性），校验失败直接 exit 1 ——
实测踩过把「门类」填进「专业类」字段的错误，靠这层拦住。

用法::

    python scripts/build_major_taxonomy_data.py
"""
import json
import pprint
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "data" / "taxonomy" / "major_taxonomy.json"
DST = REPO_ROOT / "backend" / "app" / "core" / "major_taxonomy_data.py"

data = json.loads(SRC.read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# ★ 重复键守卫（2026-09 实测踩到）
# ---------------------------------------------------------------------------
# JSON 允许同一对象出现重复键，解析器**取最后一个** —— 于是分批追加条目时，
# 后写入的值会**静默覆盖**先写入的值。实测 major_exact 里积了 554 个重复键，
# 其中 7 个值冲突（专业名被归错类，且没有任何报错）。
# 这里用 object_pairs_hook **逐对象**检测（嵌套对象里的同名键如 9 个方向类型
# 各自的 label 不会被误报），发现重复直接 exit 1。
_duplicates: dict[str, list[object]] = {}


def _dup_hook(pairs):
    seen: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            _duplicates.setdefault(key, []).append(seen[key])
            _duplicates[key].append(value)
        seen[key] = value
    return seen


json.loads(SRC.read_text(encoding="utf-8"), object_pairs_hook=_dup_hook)
if _duplicates:
    print("★ 规则库 JSON 存在重复键（后者会静默覆盖前者）：")
    for key, values in sorted(_duplicates.items()):
        uniq: list[object] = []
        for v in values:
            if v not in uniq:
                uniq.append(v)
        tag = "值冲突" if len(uniq) > 1 else "值相同"
        print(f"  [{tag}] {key!r}: {uniq}")
    print("\n请先跑 scripts/dedupe_major_taxonomy.py 消解，再重跑本脚本。")
    raise SystemExit(1)
print("重复键守卫：通过（0 个重复键）")

header = '''"""专业分类规则库数据（四级：门类 → 专业类 → 专业 → 招生方向）。

★ 本文件是**数据**，不是逻辑。判定逻辑在 :mod:`app.core.major_taxonomy`。
★ 为什么是 Python 模块而不是 JSON：``core/`` 禁止文件 IO（ADR-003），
  静态参考数据一律以模块常量形式内联 —— 与 ``scoring.CITY_TIERS`` /
  ``scoring.RELATED_CATEGORY_MAP`` 的做法一致。
★ 人类可读的规则说明与来源见 ``docs/MAJOR_TAXONOMY.md``。

**本文件由 ``scripts/build_major_taxonomy_data.py`` 从
``data/taxonomy/major_taxonomy.json`` 生成，请勿手改 —— 改 JSON 后重跑脚本。**
"""

from __future__ import annotations

'''

parts = [header]
order = [
    "BENKE_CATEGORIES",
    "ZHUANKE_CATEGORIES",
    "DISCIPLINE_KEYWORDS",
    "MAJOR_EXACT",
    "MAJOR_EXACT_BY_LEVEL",
    "DIRECTION_KINDS",
    "TRAINING_CLASS_RULES",
    "DIRECTION_NARROWING",
    "DIRECTION_CATEGORY",
    "SOURCE",
]
mapping = {
    "BENKE_CATEGORIES": "benke_categories",
    "ZHUANKE_CATEGORIES": "zhuanke_categories",
    "DISCIPLINE_KEYWORDS": "discipline_keywords",
    "MAJOR_EXACT": "major_exact",
    "MAJOR_EXACT_BY_LEVEL": "major_exact_by_level",
    "DIRECTION_KINDS": "direction_kinds",
    "TRAINING_CLASS_RULES": "training_class_rules",
    "DIRECTION_NARROWING": "direction_narrowing",
    "DIRECTION_CATEGORY": "direction_category",
}

meta = data["_meta"]
parts.append("SOURCE: dict[str, object] = ")
parts.append(pprint.pformat(meta, width=100, sort_dicts=False))
parts.append("\n\n")

for const in order[:-1]:
    key = mapping[const]
    parts.append(f"{const} = ")
    parts.append(pprint.pformat(data[key], width=100, sort_dicts=False))
    parts.append("\n\n")

parts.append('__all__ = [\n')
for const in order:
    parts.append(f'    "{const}",\n')
parts.append("]\n")

DST.write_text("".join(parts), encoding="utf-8")
print(f"写出 {DST} ({DST.stat().st_size} bytes)")

# 校验：重新 import 后与原 JSON 等价
sys.path.insert(0, r"D:\exam_select\backend")
from app.core import major_taxonomy_data as mod  # noqa: E402

for const, key in mapping.items():
    got = getattr(mod, const)
    want = data[key]
    assert got == want, f"{const} 不一致"
print("等价性校验通过：所有常量与 JSON 完全一致")

# ---------------------------------------------------------------------------
# 不变量校验（★ 拦住"把门类当专业类填"这类数据错误）
# ---------------------------------------------------------------------------
discipline_to_category = {
    d: c for c, ds in data["benke_categories"].items() for d in ds
}
discipline_to_category.update(
    {d: c for c, ds in data["zhuanke_categories"].items() for d in ds}
)
benke_categories = set(data["benke_categories"])
zhuanke_categories = set(data["zhuanke_categories"])

errors: list[str] = []

# 1) DIRECTION_NARROWING 的值必须是**专业类**（不能是门类）
for kw, value in data["direction_narrowing"].items():
    if value not in discipline_to_category:
        errors.append(
            f"direction_narrowing['{kw}'] = '{value}' 不是合法专业类"
            + ("（它是门类！应放进 direction_category）" if value in benke_categories else "")
        )

# 2) DIRECTION_CATEGORY 的值必须是**门类**
for kw, value in data["direction_category"].items():
    if value not in benke_categories:
        errors.append(f"direction_category['{kw}'] = '{value}' 不是合法门类")

# 3) TRAINING_CLASS_RULES 的值必须是**门类**
for name, value in data["training_class_rules"].items():
    if value not in benke_categories:
        errors.append(f"training_class_rules['{name}'] = '{value}' 不是合法门类")

# 4) MAJOR_EXACT 的值必须是**专业类**
for name, value in data["major_exact"].items():
    if value not in discipline_to_category:
        errors.append(f"major_exact['{name}'] = '{value}' 不是合法专业类")

# 5) DISCIPLINE_KEYWORDS 的键必须是**专业类**
for discipline in data["discipline_keywords"]:
    if discipline not in discipline_to_category:
        errors.append(f"discipline_keywords 的键 '{discipline}' 不是合法专业类")

# 6) 专业类不得重名跨门类（否则 category_of 会有歧义）
seen: dict[str, str] = {}
for category, disciplines in data["benke_categories"].items():
    for d in disciplines:
        if d in seen:
            errors.append(f"专业类 '{d}' 同时属于 {seen[d]} 与 {category}")
        seen[d] = category

# 7) major_exact_by_level：键必须是 major_exact 里已有的名字，值必须是合法专业类，
#    学制键只能是 BENKE / ZHUANKE（否则永远不会被命中，是死规则）
valid_levels = {"BENKE", "ZHUANKE"}
for name, levels in data.get("major_exact_by_level", {}).items():
    if name not in data["major_exact"]:
        errors.append(f"major_exact_by_level['{name}'] 在 major_exact 里没有对应条目（永远命中不了）")
    for level, discipline in levels.items():
        if level not in valid_levels:
            errors.append(f"major_exact_by_level['{name}'] 的学制键 '{level}' 非法（只能是 BENKE/ZHUANKE）")
        if discipline not in discipline_to_category:
            errors.append(f"major_exact_by_level['{name}']['{level}'] = '{discipline}' 不是合法专业类")

if errors:
    print("\n★ 不变量校验失败：")
    for e in errors:
        print("  -", e)
    raise SystemExit(1)

print(
    f"不变量校验通过："
    f"{len(data['direction_narrowing'])} 条专业类收窄 / "
    f"{len(data['direction_category'])} 条门类收窄 / "
    f"{len(data['training_class_rules'])} 条试验班 / "
    f"{len(data['major_exact'])} 条精确名 / "
    f"{len(data['discipline_keywords'])} 个专业类关键词表 / "
    f"{len(discipline_to_category)} 个专业类"
)


# ---------------------------------------------------------------------------
# 生成文档附录（★ 让"哪个专业类属于哪个门"对**人**也是明确的，且不会与数据漂移）
# ---------------------------------------------------------------------------
DOC = REPO_ROOT / "docs" / "MAJOR_TAXONOMY.md"
MARKER_BENKE = "benke-discipline-table"
MARKER_ZHUANKE = "zhuanke-category-table"


def _replace_block(text: str, marker: str, body: str) -> str:
    begin = f"<!-- BEGIN GENERATED: {marker} -->"
    end = f"<!-- END GENERATED: {marker} -->"
    if begin not in text or end not in text:
        raise SystemExit(f"★ 文档里找不到生成标记 {marker}，无法写入附录")
    head, rest = text.split(begin, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{begin}\n{body}\n{end}{tail}"


def _benke_table() -> str:
    """12 门类 × 93 专业类，并标出每个专业类在真实语料里的命中数（便于发现冷门项）。"""
    lines = [
        "| 门类 | 专业类 | 专业类数 |",
        "|---|---|---|",
    ]
    for category, disciplines in data["benke_categories"].items():
        joined = "、".join(f"`{d}`" for d in disciplines)
        lines.append(f"| **{category}** | {joined} | {len(disciplines)} |")
    total = sum(len(v) for v in data["benke_categories"].values())
    lines.append(f"| **合计** | 12 门类 | **{total}** |")
    return "\n".join(lines)


def _zhuanke_table() -> str:
    lines = [
        "| 大类 | 专业类 |",
        "|---|---|",
    ]
    for category, disciplines in data["zhuanke_categories"].items():
        joined = "、".join(f"`{d}`" for d in disciplines)
        lines.append(f"| **{category}** | {joined} |")
    total = sum(len(v) for v in data["zhuanke_categories"].values())
    lines.append(f"| **合计** | 19 大类 / {total} 专业类 |")
    return "\n".join(lines)


doc_text = DOC.read_text(encoding="utf-8")
doc_text = _replace_block(doc_text, MARKER_BENKE, _benke_table())
doc_text = _replace_block(doc_text, MARKER_ZHUANKE, _zhuanke_table())
DOC.write_text(doc_text, encoding="utf-8")
print(f"文档附录已同步：{DOC} ({DOC.stat().st_size} bytes)")

print("SOURCE:", json.dumps(mod.SOURCE, ensure_ascii=False)[:120], "...")