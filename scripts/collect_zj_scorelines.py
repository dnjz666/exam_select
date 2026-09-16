"""浙江省普通类第一段平行投档分数线表 —— 采集与规范化（M6 数据接入的前置步骤）。

⚠️ **本脚本只做"采集 → 规范化 → 落盘"，不写数据库**。入库是 M6 的工作，
   用户明确要求先只把数据打包好。

口径（与 `docs/DATA_DICTIONARY.md` 对齐）
--------------------------------------
原始列：``学校代号 | 学校名称 | 专业代号 | 专业名称 | 计划数 | 分数线 | 位次``
→ 规范化后：
  ``year, college_code, college_name, major_code, major_name, plan_count, min_score, min_rank``
其中 ``min_rank`` 就是本项目 ``admission_history.min_rank`` 的口径（**越小越靠前**），
``min_score`` 即投档最低分。**官方原文直接给出位次，无需反查**（data_quality = OK）。

用法::

    python scripts/collect_zj_scorelines.py register-local <xls路径> --year 2024
    python scripts/collect_zj_scorelines.py build            # 解析 data/raw 下的全部年份
    python scripts/collect_zj_scorelines.py report           # 打印汇总与院校清单
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import xlrd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "zhejiang"
MANIFEST = RAW_DIR / "manifest.json"
OUT_DIR = ROOT / "data" / "normalized" / "zhejiang"

EXPECTED_HEADER = ["学校代号", "学校名称", "专业代号", "专业名称", "计划数", "分数线", "位次"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell(sheet: xlrd.sheet.Sheet, row: int, col: int) -> str:
    value = sheet.cell_value(row, col)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _pad(code: str, width: int) -> str:
    """代号补零：Excel 会把 ``0001`` 读成 ``1``，必须补回 4/3 位。"""
    digits = re.sub(r"\D", "", code)
    return digits.zfill(width) if digits else ""


def parse_workbook(path: Path) -> tuple[list[dict], list[str], list[str]]:
    """解析单个年度工作簿，返回 ``(rows, problems, footers)``。

    ``footers`` 收集表尾的非数据行（"合计"行、官方注释行）。**注释行必须留档**：
    2026 年表的表尾原文写着「注：位次栏目为空的，表示该学校专业本轮投档人数未满。」
    —— 这正是本数据里 1,857 行位次为空的原因，也是 M6 必须把它们标成
    ``MISSING_RANK`` 且**不参与概率计算**的官方依据（DOMAIN_RULES §2.2 / §6.2 Step 1）。
    """
    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    problems: list[str] = []
    footers: list[str] = []

    header = [_cell(sheet, 0, col) for col in range(sheet.ncols)]
    if header[: len(EXPECTED_HEADER)] != EXPECTED_HEADER:
        problems.append(f"表头与预期不符：{header}")

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index in range(1, sheet.nrows):
        college_code = _pad(_cell(sheet, index, 0), 4)
        college_name = _cell(sheet, index, 1)
        major_code = _pad(_cell(sheet, index, 2), 3)
        major_name = _cell(sheet, index, 3)
        plan_raw = _cell(sheet, index, 4)
        score_raw = _cell(sheet, index, 5)
        rank_raw = _cell(sheet, index, 6)

        # 学校代号为空 = 非数据行（合计行 / 官方注释行）→ 留档，不当数据
        if not college_code:
            text = " ".join(part for part in (college_name, major_name, score_raw) if part)
            if text:
                footers.append(text)
            continue
        if not college_name:
            problems.append(f"第 {index + 1} 行有代号无校名：{college_code!r}")
            continue

        key = (college_code, major_code)
        if key in seen:
            problems.append(f"第 {index + 1} 行与前面重复：{college_code}-{major_code}")
        seen.add(key)

        rows.append(
            {
                "college_code": college_code,
                "college_name": college_name,
                "major_code": major_code,
                "major_name": major_name,
                "plan_count": int(plan_raw) if plan_raw.isdigit() else None,
                "min_score": int(score_raw) if score_raw.isdigit() else None,
                "min_rank": int(rank_raw) if rank_raw.isdigit() else None,
            }
        )
    return rows, problems, footers


def cmd_register_local(args: argparse.Namespace) -> int:
    """把本地拿到的原始文件登记进 ``data/raw/zhejiang/<year>/`` 并记录 sha256。"""
    source = Path(args.path)
    if not source.is_file():
        print(f"文件不存在：{source}")
        return 1
    target_dir = RAW_DIR / str(args.year)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    target.write_bytes(source.read_bytes())

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    entry = manifest.setdefault(f"{args.year}", {"files": []})
    entry.setdefault("files", []).append(
        {
            "file": str(target.relative_to(ROOT)).replace("\\", "/"),
            "sha256": _sha256(target),
            "bytes": target.stat().st_size,
            "source_url": args.source_url or "",
            "note": args.note or "",
        }
    )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已登记 {args.year}：{target.relative_to(ROOT)}  sha256={_sha256(target)[:16]}…")
    return 0


def _iter_raw_files() -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    if not RAW_DIR.exists():
        return found
    for year_dir in sorted(RAW_DIR.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for path in sorted(year_dir.iterdir()):
            if path.suffix.lower() in (".xls", ".xlsx"):
                found.append((int(year_dir.name), path))
    return found


def cmd_build(_: argparse.Namespace) -> int:
    """解析全部年度 → 规范化 CSV（UTF-8 BOM，Excel 直接可开）+ 年度统计。"""
    files = _iter_raw_files()
    if not files:
        print(f"data/raw/zhejiang 下没有原始文件；先用 register-local 登记")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    all_rows: list[dict] = []

    for year, path in files:
        rows, problems, footers = parse_workbook(path)
        for row in rows:
            row["year"] = year
        all_rows.extend(rows)
        colleges = {row["college_code"] for row in rows}
        out = OUT_DIR / f"zhejiang_parallel_seg1_{year}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "year",
                    "college_code",
                    "college_name",
                    "major_code",
                    "major_name",
                    "plan_count",
                    "min_score",
                    "min_rank",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
        summary[str(year)] = {
            "source_file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "rows": len(rows),
            "colleges": len(colleges),
            "plan_total": sum(row["plan_count"] or 0 for row in rows),
            "score_range": [
                min((r["min_score"] for r in rows if r["min_score"]), default=None),
                max((r["min_score"] for r in rows if r["min_score"]), default=None),
            ],
            "rank_range": [
                min((r["min_rank"] for r in rows if r["min_rank"]), default=None),
                max((r["min_rank"] for r in rows if r["min_rank"]), default=None),
            ],
            "missing_rank": sum(1 for r in rows if r["min_rank"] is None),
            "missing_score": sum(1 for r in rows if r["min_score"] is None),
            "problems": problems[:20],
            "problem_count": len(problems),
            "footers": footers,
            "csv": str(out.relative_to(ROOT)).replace("\\", "/"),
        }
        print(
            f"{year}: {len(rows):>6} 行 · {len(colleges):>4} 所院校 · "
            f"计划合计 {summary[str(year)]['plan_total']:>6} · 问题 {len(problems)}"
        )

    # 跨年院校清单（供寝室/校园环境采集使用）
    by_year: dict[int, set[tuple[str, str]]] = {}
    for row in all_rows:
        by_year.setdefault(row["year"], set()).add((row["college_code"], row["college_name"]))

    schools: dict[tuple[str, str], set[int]] = {}
    for year, pairs in by_year.items():
        for pair in pairs:
            schools.setdefault(pair, set()).add(year)

    school_csv = OUT_DIR / "zhejiang_colleges_by_year.csv"
    with school_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["college_code", "college_name", "years", "year_count"])
        for (code, name), years in sorted(schools.items(), key=lambda kv: kv[0][0]):
            writer.writerow([code, name, ",".join(str(y) for y in sorted(years)), len(years)])

    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n跨年院校合计 {len(schools)} 所 → {school_csv.relative_to(ROOT)}")
    return 0


def cmd_report(_: argparse.Namespace) -> int:
    summary_path = OUT_DIR / "summary.json"
    if not summary_path.exists():
        print("还没有 summary.json，先跑 build")
        return 1
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for year, item in sorted(summary.items()):
        print(
            f"{year}: {item['rows']:>6} 行 · {item['colleges']:>4} 所 · "
            f"分数 {item['score_range']} · 位次 {item['rank_range']} · "
            f"缺位次 {item['missing_rank']} · 问题 {item['problem_count']}"
        )
    codes = Counter()
    csv_path = OUT_DIR / "zhejiang_colleges_by_year.csv"
    if csv_path.exists():
        with csv_path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                codes[row["year_count"]] += 1
        print(f"\n院校跨年出现次数分布（出现 N 年的院校数）：{dict(sorted(codes.items()))}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="浙江投档分数线表采集与规范化（不入库）")
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register-local", help="登记本地已拿到的原始文件")
    register.add_argument("path")
    register.add_argument("--year", type=int, required=True)
    register.add_argument("--source-url", default="")
    register.add_argument("--note", default="")
    register.set_defaults(func=cmd_register_local)

    sub.add_parser("build", help="解析并产出规范化 CSV").set_defaults(func=cmd_build)
    sub.add_parser("report", help="打印汇总").set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
