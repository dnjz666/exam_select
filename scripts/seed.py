"""一键生成并载入确定性模拟数据（M1，**幂等**）。

用法::

    backend\\.venv\\Scripts\\python.exe scripts\\seed.py --reset   # 重建全部表后入库
    backend\\.venv\\Scripts\\python.exe scripts\\seed.py           # 重跑：先清模拟行再入库，计数不变

幂等语义
--------
本脚本只负责 ``is_synthetic=1`` 的数据：每次运行先删除全部模拟行，再整批写入。
因此重复执行结果完全一致（计数与内容摘要都相同），也不会误删 M6 之后的真实数据。

★ 合规：生成的数据全部为模拟值（``verified=0``），**严禁用于真实志愿填报**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许未安装包时直接运行（AGENTS.md §4.4 的验收命令形式）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

from sqlalchemy import delete, func, insert, select  # noqa: E402

from app.db import models as db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.etl.synthetic import SEED, generate  # noqa: E402

#: 写入顺序：被引用者在前（无外键约束，但保持可读的层次）
_TABLES = (
    ("score_rank_table", db.ScoreRankTable),
    ("province_year_stats", db.ProvinceYearStats),
    ("colleges", db.College),
    ("majors", db.Major),
    ("admission_units", db.AdmissionUnitRow),
    ("admission_plans", db.AdmissionPlan),
    ("admission_history", db.AdmissionHistory),
)
_CHUNK = 1000


def _clear_synthetic(session) -> None:
    """删除全部模拟行（保留 is_synthetic=0 的真实数据）。"""
    # 删除顺序与写入顺序相反：先删下游
    for _, model in reversed(_TABLES):
        session.execute(delete(model).where(model.is_synthetic.is_(True)))


def _bulk_insert(session, model, rows: list[dict]) -> None:
    for start in range(0, len(rows), _CHUNK):
        session.execute(insert(model), rows[start : start + _CHUNK])


def _counts(session) -> dict[str, int]:
    return {
        name: session.execute(select(func.count()).select_from(model)).scalar_one()
        for name, model in _TABLES
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成并载入确定性模拟数据（M1）")
    parser.add_argument("--reset", action="store_true", help="先 drop_all + create_all，再入库")
    parser.add_argument("--seed", type=int, default=SEED, help=f"随机种子（默认 {SEED}）")
    args = parser.parse_args(argv)

    if args.reset:
        Base.metadata.drop_all(engine)
        print("[seed] --reset：已删除全部表")
    Base.metadata.create_all(engine)

    dataset = generate(args.seed)
    print(f"[seed] 生成完成（seed={args.seed}）摘要={dataset.digest()[:16]}")
    for name, count in dataset.counts().items():
        print(f"        {name:<22} {count:>7}")
    print("[seed] 注入样本：" + "，".join(f"{k}={len(v)}" for k, v in sorted(dataset.injections.items())))

    with SessionLocal() as session:
        _clear_synthetic(session)
        session.flush()
        for name, model in _TABLES:
            _bulk_insert(session, model, getattr(dataset, name))
        session.commit()
        counts = _counts(session)

    print("[seed] 入库后库内计数：")
    for name, count in counts.items():
        print(f"        {name:<22} {count:>7}")

    expected = dataset.counts()
    mismatch = {k: (v, counts[k]) for k, v in expected.items() if counts[k] != v}
    if mismatch:
        print(f"[seed] ✗ 入库计数与生成计数不一致：{mismatch}")
        return 1
    print("[seed] ✓ 幂等完成：库内计数与生成计数一致（重复运行结果不变）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
