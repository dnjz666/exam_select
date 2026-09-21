"""把专业目录归属（门类 / 专业类）回填进**已有**数据库（ADR-018）。

## 为什么需要这个脚本

``etl/loaders/zhejiang.py`` 已在装载时回填，但那只对**新播种**的数据生效。
``seed.py --reset`` 会连带清空考生档案、志愿表与对话（并让浏览器里的草稿 id 失效）。
本脚本做**定向、幂等**的原地回填：只补 ``category``/``discipline`` 为空的行，
不碰任何用户数据，可安全重复执行。

## 口径

* 只处理 ``category`` 与 ``discipline`` **同时为空**的行（已有的不动，尊重原口径）；
* 门类/专业类由 ``core.major_taxonomy.classify_major`` 确定性推出；
* 分类器定不出来的行**保持为空** —— 宁可不答，不可编造；
* 默认只更新真实数据行（``is_synthetic=0``）；``--include-synthetic`` 可一并处理。

用法::

    python scripts/backfill_major_taxonomy.py            # 预演（只补空值）
    python scripts/backfill_major_taxonomy.py --apply    # 实际写库
    python scripts/backfill_major_taxonomy.py --apply --include-synthetic

    # ★ 规则库改动后，重新归类**已有**行（会改已有值，先预演看清 diff）
    python scripts/backfill_major_taxonomy.py --reclassify
    python scripts/backfill_major_taxonomy.py --reclassify --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# Windows 控制台默认不是 UTF-8，中文输出会乱码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select  # noqa: E402

from app.core.major_taxonomy import classify_major  # noqa: E402
from app.db import models as db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _level_of(duration: int | None) -> str | None:
    from app.core.major_taxonomy import LEVEL_BENKE, LEVEL_ZHUANKE

    if duration == 3:
        return LEVEL_ZHUANKE
    if duration:
        return LEVEL_BENKE
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="回填专业门类/专业类（ADR-018）")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认只预演）")
    parser.add_argument(
        "--include-synthetic", action="store_true", help="连模拟数据行一起处理"
    )
    parser.add_argument(
        "--reclassify",
        action="store_true",
        help="重新归类**已有**行（规则库改动后用；只补空值的默认模式不会覆盖已有值）",
    )
    args = parser.parse_args()

    updated = 0
    skipped_unclassified = 0
    reclassified = 0
    status_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    samples: list[tuple[str, str | None, str | None]] = []
    diffs: list[tuple[str, str | None, str | None, str | None, str | None]] = []

    with SessionLocal() as session:
        stmt = select(db.Major)
        if not args.reclassify:
            # 默认模式：只补两个字段同时为空的行（尊重已有口径）
            stmt = stmt.where(
                db.Major.category.is_(None), db.Major.discipline.is_(None)
            )
        if not args.include_synthetic:
            stmt = stmt.where(db.Major.is_synthetic == 0)
        rows = list(session.execute(stmt).scalars())
        mode = "重新归类已有行" if args.reclassify else "只补空值"
        print(f"待处理行数（{mode}）= {len(rows)}")

        for row in rows:
            taxonomy = classify_major(row.name, level=_level_of(row.duration))
            status_counter[taxonomy.status.value] += 1
            if not taxonomy.is_classified:
                skipped_unclassified += 1
                continue
            category_counter[taxonomy.category or "(仅专业类)"] += 1
            if len(samples) < 10:
                samples.append((row.name, taxonomy.category, taxonomy.discipline))

            # 在 reclassify 模式下，只更新**真正变化**的行，并记录 diff
            changed = (row.category, row.discipline) != (
                taxonomy.category,
                taxonomy.discipline,
            )
            if args.reclassify:
                if not changed:
                    continue
                if len(diffs) < 40:
                    diffs.append(
                        (
                            row.name,
                            row.category,
                            row.discipline,
                            taxonomy.category,
                            taxonomy.discipline,
                        )
                    )
                reclassified += 1
            if args.apply:
                row.category = taxonomy.category
                row.discipline = taxonomy.discipline
            updated += 1

        if args.apply:
            session.commit()
            # 写库后让进程内缓存失效（ADR-016）：否则会继续读到旧的门类/专业类
            from app.db import repositories

            repositories.bump_generation()

    print()
    print("=== 判定来源分布 ===")
    for status, count in sorted(status_counter.items()):
        print(f"  {status:<20} {count:>6}")
    print()
    print("=== 回填后的门类分布 ===")
    for category, count in category_counter.most_common():
        print(f"  {category:<12} {count:>6}")
    print()
    print("样例：")
    for name, category, discipline in samples:
        print(f"  {name[:44]:<46} 门类={category}  专业类={discipline}")

    if args.reclassify and diffs:
        print()
        print(f"=== 归类发生变化的行（最多显示 40 条，共 {reclassified} 条）===")
        for name, oc, od, nc, nd in diffs:
            print(f"  {name[:40]:<42} {oc}/{od}  →  {nc}/{nd}")

    print()
    verb = "已写入" if args.apply else "预演：将写入"
    print(
        f"{verb} {updated} 行；分类器定不出来而保持为空 {skipped_unclassified} 行"
        "（宁可不答，不可编造）"
    )
    if not args.apply:
        print("（未加 --apply，数据库未改动）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())