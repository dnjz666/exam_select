"""一键生成并载入数据（M1 模拟数据 / M6 真实数据，**幂等**）。

用法::

    backend\\.venv\\Scripts\\python.exe scripts\\seed.py --reset          # 重建全部表后入库
    backend\\.venv\\Scripts\\python.exe scripts\\seed.py --source synthetic # 只灌六省模拟数据
    backend\\.venv\\Scripts\\python.exe scripts\\seed.py --source real      # 只灌浙江真实数据
    backend\\.venv\\Scripts\\python.exe scripts\\seed.py                  # hybrid（默认）：
                                                                        #   浙江=真实、其余五省=模拟

幂等语义
--------
* 模拟行（``is_synthetic=1``）每次运行先整批删除再写入 → 重复执行计数与内容完全一致；
* 真实行（``is_synthetic=0`` 且 ``province='zhejiang'``）同理先删后写（ADR-015），
  因此 ``--source real`` 也可以反复执行；
* 两种模式都**不会**碰考生档案（students）、志愿表（plans）与对话（chat_messages）。

★ 合规（AGENTS.md §12）
-----------------------
* ``--source synthetic`` 的数据全部为模拟值（``verified=0``），**严禁用于真实志愿填报**；
* ``--source real`` 的数据来自浙江省教育考试院公开发布物（来源 URL 见每行的
  ``source_url`` 与 ``data/raw/zhejiang/manifest.json``），但**仍只是辅助参考**，
  最终以考试院官方文件与招生章程为准。
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

from app.core.models import unit_key_of  # noqa: E402
from app.db import models as db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.etl.loaders.zhejiang import PROVINCE as REAL_PROVINCE  # noqa: E402
from app.etl.loaders.zhejiang import load_zhejiang  # noqa: E402
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

#: ``RealZhejiangDataset`` 的属性名与表名不同（它保留了合成数据集的字段命名习惯），
#: 这里显式映射，避免用 ``getattr`` 猜。
_REAL_ATTR = {
    "score_rank_table": "score_rank_table",
    "province_year_stats": "province_year_stats",
    "colleges": "college_rows",
    "majors": "major_rows",
    "admission_units": "admission_units",
    "admission_plans": "admission_plans",
    "admission_history": "admission_history",
}

#: 真实数据的标记（ADR-015）：source_url 前缀；真实行的识别**只认它**
_REAL_PREFIX = "real://%"


def _drop_province(rows: list[dict], province: str) -> list[dict]:
    """从模拟数据集中剔掉某个省（hybrid 模式下该省由真实数据接管）。

    ★ 为什么必须剔干净：``colleges`` 主键是 ``{province}-{院校代号}``、
    ``score_rank_table`` 有 ``UNIQUE(province, year, track, score)`` —— 模拟侧与真实侧
    都会用同一套 id/唯一键。不剔干净会出现两种脏数据：
    ① 同一 (省, 年, 分数) 撞唯一键导致入库失败；
    ② 同一所院校被算成两所（模拟的"浙江大学"与真实的"浙江大学"并存）。
    """
    return [row for row in rows if row.get("province") != province]


def _drop_by_unit_key(rows: list[dict], province: str) -> list[dict]:
    """``admission_plans`` / ``admission_history`` **没有 province 列**，只能看 unit_key 前缀。

    这两个表的 ``source_url`` 是 ``synthetic://``，但 ``unit_key`` 形如
    ``zhejiang-1001-NA-100106`` —— 省前缀就是第一段。不剔掉它们，被剔掉的浙江单位会
    留下孤儿计划/历史（``PLAN_ORPHAN`` / ``HISTORY_ORPHAN``）。
    """
    prefix = f"{province}-"
    return [
        row
        for row in rows
        if not (
            str(row.get("unit_key", "")).startswith(prefix)
            or row.get("college_id", "").startswith(prefix)
            or row.get("province") == province
        )
    ]


#: 哪些模拟数据表需要按哪种方式剔省
_DROP_BY_UNIT_KEY = ("admission_plans", "admission_history")


def _drop_orphan_units(rows: list[dict], kept_college_ids: set[str]) -> list[dict]:
    """剔掉院校已不在库里的投档单位。

    ★ 为什么需要：``admission_units.college_id`` 是外键（``{省}-{院校代号}``），而
    ``colleges`` 里**并不是每个省都有全部院校**（例如浙江的院校行只挂在 zhejiang 名下）。
    hybrid 模式剔掉 zhejiang 的模拟院校后，北京/上海的模拟单位仍可能引用
    ``zhejiang-1387`` 这类已删院校 → ``COLLEGE_REF_MISSING``（M6 实测 137 条）。
    """
    return [row for row in rows if row.get("college_id") in kept_college_ids]


def _clear_synthetic(session) -> None:
    """删除**模拟行**（保留真实行）。

    ★ 判据必须同时看 ``is_synthetic`` 与 ``source_url``：浙江的 2023–2025 一分一段表
    虽然是"锚定式模拟分布"（``is_synthetic=1``），但它是**真实数据装载器**产出的、
    与真实行同属 ``real://`` 命名空间，且与真实的 ``colleges`` / ``admission_units``
    共享主键。若按 ``is_synthetic`` 一把删，会连带删掉为它做外键锚定的真实行，
    随后重新插入时撞主键（M6 实测踩到）。
    """
    # 删除顺序与写入顺序相反：先删下游
    for _, model in reversed(_TABLES):
        session.execute(
            delete(model).where(model.is_synthetic.is_(True), model.source_url.not_like(_REAL_PREFIX))
        )


def _clear_real(session, province: str) -> None:
    """删除真实行（先删下游表）。

    ★ 判据只有一条：``source_url`` 以 ``real://`` 开头。**不能**再加"省 == 浙江"的
    条件——真实院校的 ``province`` 是**院校所在地**（浙江考生能报的院校遍布全国），
    加省份条件会让 1663 所外省院校留成孤儿行，下次入库直接撞主键（M6 实测踩到）。
    考生档案与志愿表不在 ``_TABLES`` 里，天然不受影响。
    """
    for _, model in reversed(_TABLES):
        session.execute(delete(model).where(model.source_url.like(_REAL_PREFIX)))


def _bulk_insert(session, model, rows: list[dict]) -> None:
    for start in range(0, len(rows), _CHUNK):
        session.execute(insert(model), rows[start : start + _CHUNK])


def _counts(session) -> dict[str, int]:
    return {
        name: session.execute(select(func.count()).select_from(model)).scalar_one()
        for name, model in _TABLES
    }


def _real_counts(session, province: str) -> dict[str, int]:
    """统计"真实行"条数。

    ★ 判据必须用 ``source_url`` 前缀而不是 ``province``：模拟数据里也有 zhejiang 的
    院校/专业（M6 之前它们就是浙江的全部数据），而真实院校的 ``province`` 表示
    **院校所在地**（可能是任何一个省），只看省份两边都会数错。
    """
    return {
        name: session.execute(
            select(func.count()).select_from(model).where(model.source_url.like(_REAL_PREFIX))
        ).scalar_one()
        for name, model in _TABLES
    }


def _require_columns(session, model, columns: tuple[str, ...]) -> list[str]:
    """检查库中表是否已有这些列（``create_all`` 不会给已存在的表加列）。

    真实数据接入（M6）给 ``province_year_stats`` 加了两列；旧的开发库直接灌真实数据会
    报一句 SQLite 的 ``no column named ...``，看不出该做什么。这里提前检查并给出
    明确指引（``--reset``），而不是让用户去读堆栈。生产环境应改用 alembic 迁移。
    """
    from sqlalchemy import inspect as sa_inspect

    existing = {column["name"] for column in sa_inspect(session.get_bind()).get_columns(model.__tablename__)}
    return [name for name in columns if name not in existing]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成并载入数据（M1 模拟 / M6 真实）")
    parser.add_argument("--reset", action="store_true", help="先 drop_all + create_all，再入库")
    parser.add_argument("--seed", type=int, default=SEED, help=f"随机种子（默认 {SEED}）")
    parser.add_argument(
        "--source",
        choices=("hybrid", "synthetic", "real"),
        default="hybrid",
        help="hybrid=浙江真实+其余模拟（默认）；synthetic=全部模拟；real=仅浙江真实",
    )
    args = parser.parse_args(argv)

    if args.reset:
        Base.metadata.drop_all(engine)
        print("[seed] --reset：已删除全部表")
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        missing = _require_columns(
            session,
            db.ProvinceYearStats,
            ("segment1_cumulative", "segment1_line"),
        )
        if missing:
            print(
                f"[seed] ✗ 库中 province_year_stats 缺列 {missing}（M6 新增，ADR-015）。\n"
                "        请先执行： backend\\.venv\\Scripts\\python.exe scripts\\seed.py --reset "
                "--source <hybrid|real>\n"
                "        （--reset 会清空考生档案 / 志愿表 / 对话，请先确认无需保留）"
            )
            return 1

    failures: list[str] = []

    with SessionLocal() as session:
        _clear_synthetic(session)
        _clear_real(session, REAL_PROVINCE)
        session.flush()

        if args.source in ("hybrid", "synthetic"):
            dataset = generate(args.seed)
            print(f"[seed] 模拟数据生成完成（seed={args.seed}）摘要={dataset.digest()[:16]}")
            expected: dict[str, int] = {}
            kept_colleges: set[str] | None = None
            kept_units: set[str] | None = None
            orphan_plans = 0
            for name, model in _TABLES:
                rows = getattr(dataset, name)
                if args.source == "hybrid":
                    rows = (
                        _drop_by_unit_key(rows, REAL_PROVINCE)
                        if name in _DROP_BY_UNIT_KEY
                        else _drop_province(rows, REAL_PROVINCE)
                    )
                    if name == "colleges":
                        kept_colleges = {row["id"] for row in rows}
                    elif name == "admission_units" and kept_colleges is not None:
                        rows = _drop_orphan_units(rows, kept_colleges)
                        kept_units = {unit_key_of(row["unit_id"]) for row in rows}
                    elif kept_units is not None and name in _DROP_BY_UNIT_KEY:
                        before = len(rows)
                        rows = [row for row in rows if row["unit_key"] in kept_units]
                        orphan_plans += before - len(rows)
                _bulk_insert(session, model, rows)
                expected[name] = len(rows)
            if args.source == "hybrid":
                print(f"[seed] hybrid 剔省清理：模拟孤儿计划/历史 {orphan_plans} 条")
            print("[seed] 注入样本：" + "，".join(f"{k}={len(v)}" for k, v in sorted(dataset.injections.items())))
            session.flush()
            real_now = _real_counts(session, REAL_PROVINCE)
            totals_now = _counts(session)
            mismatch = {
                key: (value, totals_now[key] - real_now.get(key, 0))
                for key, value in expected.items()
                if totals_now[key] - real_now.get(key, 0) != value
            }
            if mismatch:
                failures.append(f"模拟数据入库计数与生成计数不一致：{mismatch}")

        if args.source in ("hybrid", "real"):
            real = load_zhejiang(_ROOT)
            print(
                f"[seed] 浙江真实数据装载完成（{real.stats['target_year']} 填报年，"
                f"历史 {'/'.join(str(y) for y in real.stats['history_years'])}）"
                f" 摘要={real.digest()[:16]}"
            )
            for name, count in real.counts().items():
                print(f"        {name:<22} {count:>7}")
            for name, model in _TABLES:
                _bulk_insert(session, model, getattr(real, _REAL_ATTR[name]))
            session.flush()
            actual = _real_counts(session, REAL_PROVINCE)
            expected_real = real.counts()
            mismatch = {
                key: (value, actual.get(key))
                for key, value in expected_real.items()
                if actual.get(key) != value
            }
            if mismatch:
                failures.append(f"真实数据入库计数与装载计数不一致：{mismatch}")
            print("[seed] 浙江真实数据缺口（如实披露，未用模拟值填充）：")
            for gap in real.gaps:
                print(f"        ! {gap}")

        session.commit()
        counts = _counts(session)
        real_counts = _real_counts(session, REAL_PROVINCE)

    print("[seed] 入库后库内计数：")
    for name, count in counts.items():
        print(f"        {name:<22} {count:>7}   （其中 {REAL_PROVINCE} 真实 {real_counts.get(name, 0):>7}）")
    if failures:
        for line in failures:
            print(f"[seed] ✗ {line}")
        return 1
    print("[seed] ✓ 幂等完成：重复运行结果不变（模拟行与浙江真实行都是先删后写）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
