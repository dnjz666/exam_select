"""消除 ``data/taxonomy/major_taxonomy.json`` 里的重复键（一次性清理 + 可复跑的守卫）。

## 背景

JSON 规范允许同一个对象里出现重复键，解析器**取最后一个**。实测该文件
``major_exact`` 里有 **554 个重复键**（开发时分批追加条目造成），其中 **7 个值冲突** ——
也就是说那 7 个专业名被**静默地**归到了后写入的（未必正确的）专业类。

值相同的 547 个是纯冗余；值冲突的 7 个必须**逐个判定**，不能靠"最后一个生效"这种巧合。

## 7 个冲突的判定（每条都有依据，不是随手挑）

| 键 | 数据里的学制 | 判定 | 依据 |
|---|---|---|---|
| `交通管理` | 本科 d=4（3 单位） | **公共管理类** | 本科目录 120407T 属公共管理类；公安技术类里叫 `交通管理工程`(083103TK)，是另一个名字 |
| `人力资源管理` | 本科 78 / 专科 6 | **本科→工商管理类；专科→公共管理类** | 本科 120206 属工商管理类；专科 590202 属公共管理与服务大类。**真实的两级分裂**，改用 `major_exact_by_level` 表达 |
| `动漫制作技术` | 专科 d=3（5 单位） | **计算机类** | 专科专业代码 510215 前缀 51 = 电子与信息大类 |
| `建筑消防技术` | 专科 d=3（3 单位） | **建筑类** | 与关键词层一致（`建筑消防`）；建筑设备方向 |
| `智慧海洋技术` | 本科 d=4（1 单位） | **海洋工程类** | 与关键词层一致（`智慧海洋`） |
| `水生态修复技术` | **数据中不存在** | **环境科学与工程类** | 关键词层原本无命中；本次**补上关键词**让两层一致（标注未在真实数据中出现） |
| `社区管理与服务` | 专科 d=3（4 单位） | **公共管理类** | 与关键词层一致（`社区管理与服务`） |

同时修掉一处**关键词层自身的歧义**：`交通管理` 原先同时出现在 `交通运输类` 与
`公共管理类` 的关键词表里，最长优先无法区分 → 从 `交通运输类` 移除
（它不是交通运输类的专业名；该类是 `交通运输`/`交通工程`/`交通设备与控制工程`）。

## 产物

* 重写 JSON：去重 + 键排序（确定性输出，重复键再也藏不住）+ 新增 `major_exact_by_level`；
* 该脚本**幂等**：重复执行不再有任何变化。

用法::

    python scripts/dedupe_major_taxonomy.py            # 预演
    python scripts/dedupe_major_taxonomy.py --apply    # 写回
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "data" / "taxonomy" / "major_taxonomy.json"

#: 7 个冲突键的**人工判定**（值 = 最终应生效的专业类）
CONFLICT_RESOLUTION: dict[str, str] = {
    "交通管理": "公共管理类",
    "人力资源管理": "工商管理类",  # 本科口径；专科由 major_exact_by_level 覆盖
    "动漫制作技术": "计算机类",
    "建筑消防技术": "建筑类",
    "智慧海洋技术": "海洋工程类",
    "水生态修复技术": "环境科学与工程类",
    "社区管理与服务": "公共管理类",
}

#: 按学制分流的条目（真实的两级分裂）
BY_LEVEL: dict[str, dict[str, str]] = {
    "人力资源管理": {"ZHUANKE": "公共管理类"},
}

#: 关键词层的歧义修正：从这些专业类的关键词表里移除该词
KEYWORD_REMOVALS: dict[str, list[str]] = {
    "交通运输类": ["交通管理"],
}

#: 关键词补充：让关键词层与 major_exact 一致
KEYWORD_ADDITIONS: dict[str, list[str]] = {
    "环境科学与工程类": ["水生态修复"],
}

#: 需要按键排序的扁平映射（确定性输出）
SORTED_SECTIONS = (
    "benke_categories",
    "zhuanke_categories",
    "discipline_keywords",
    "major_exact",
    "training_class_rules",
    "direction_narrowing",
    "direction_category",
    "major_exact_by_level",
)


def find_duplicates(text: str) -> dict[str, list[object]]:
    """★ 逐对象检测重复键（不是全文扁平扫描）。

    ``object_pairs_hook`` 每次收到的是**同一个对象**的全部键值对，
    因此嵌套对象里的同名键（如 9 个方向类型各自的 ``label``）不会被误报。
    """
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


def main() -> int:
    parser = argparse.ArgumentParser(description="消除专业分类规则库的重复键")
    parser.add_argument("--apply", action="store_true", help="写回文件（默认只预演）")
    args = parser.parse_args()

    original = SRC.read_text(encoding="utf-8")
    dups = find_duplicates(original)

    print(f"文件：{SRC}")
    print(f"检测到重复键：{len(dups)} 个")
    if not dups:
        print("✓ 没有重复键，无需处理。")
        return 0

    # 分类：值相同 / 值冲突
    conflicts: dict[str, list[object]] = {}
    same: list[str] = []
    for key, values in dups.items():
        uniq: list[object] = []
        for v in values:
            if v not in uniq:
                uniq.append(v)
        if len(uniq) > 1:
            conflicts[key] = uniq
        else:
            same.append(key)

    print(f"  值相同（纯冗余）：{len(same)}")
    print(f"  值冲突（真错误）：{len(conflicts)}")
    print()

    unexpected = sorted(set(conflicts) - set(CONFLICT_RESOLUTION))
    if unexpected:
        print("★ 出现**未登记**的冲突键，请先人工判定后再跑本脚本：")
        for key in unexpected:
            print(f"    {key}: {conflicts[key]}")
        return 1

    print("=== 冲突键判定 ===")
    for key in sorted(conflicts):
        print(f"  {key:<16} {conflicts[key]}  →  采用 {CONFLICT_RESOLUTION[key]!r}")
    print()

    # ---- 构造去重后的结构 ----
    data = json.loads(original)
    changed: list[str] = []

    exact = data["major_exact"]
    for key, value in CONFLICT_RESOLUTION.items():
        if exact.get(key) != value:
            changed.append(f"major_exact[{key!r}]: {exact.get(key)!r} → {value!r}")
            exact[key] = value
    # 值相同的重复项：json.loads 已按"最后生效"取了一个，这里显式确认无遗漏
    print(f"major_exact 条目数（去重后）：{len(exact)}")

    # 关键词修正
    for discipline, words in KEYWORD_REMOVALS.items():
        bucket = data["discipline_keywords"][discipline]
        for word in words:
            if word in bucket:
                bucket.remove(word)
                changed.append(f"discipline_keywords[{discipline!r}] 移除关键词 {word!r}")
    for discipline, words in KEYWORD_ADDITIONS.items():
        bucket = data["discipline_keywords"][discipline]
        for word in words:
            if word not in bucket:
                bucket.append(word)
                changed.append(f"discipline_keywords[{discipline!r}] 新增关键词 {word!r}")

    # 按学制分流
    data["major_exact_by_level"] = {
        name: dict(levels) for name, levels in sorted(BY_LEVEL.items())
    }
    changed.append(f"新增 major_exact_by_level（{len(BY_LEVEL)} 条）")

    # 排序扁平映射（确定性输出）
    for section in SORTED_SECTIONS:
        if section in data:
            data[section] = {k: data[section][k] for k in sorted(data[section])}

    # _meta.caveats 追加本次清理说明
    caveat = (
        "2026-09 清理：major_exact 原有 554 个重复键（JSON 取最后一个，"
        "导致 7 个专业名被静默归错类）。已去重 + 逐条判定冲突 + 键排序；"
        "build_major_taxonomy_data.py 现在会在出现重复键时直接失败。"
    )
    if caveat not in data["_meta"]["caveats"]:
        data["_meta"]["caveats"].append(caveat)

    print()
    print("=== 将发生的改动 ===")
    for line in changed:
        print(f"  · {line}")

    new_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    # 自检：新文本必须无重复键
    leftover = find_duplicates(new_text)
    if leftover:
        print(f"★ 去重后仍有重复键：{list(leftover)}")
        return 1
    print()
    print("✓ 自检通过：去重后的文本没有任何重复键")

    if args.apply:
        SRC.write_text(new_text, encoding="utf-8")
        print(f"✓ 已写回 {SRC}（{len(original)} → {len(new_text)} chars）")
    else:
        print("（未加 --apply，文件未改动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
