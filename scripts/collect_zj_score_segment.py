"""浙江省「普通高校招生成绩分数段表（总分）」采集与规范化（M6 一分一段表来源）。

为什么必须单独做这一步
----------------------
``score_rank_table``（一分一段表）是**位次法的地基**：分数→位次换算、跨年位次归一化
都依赖它（AGENTS.md §6.1）。M0–M5 用的是模拟表；M6 接入真实数据时，
这张表**必须来自考试院官方发布物**，不能由投档分数线表反推（那会低估分母）。

来源（均为浙江省教育考试院官网公开发布物）
------------------------------------------
* 文章页：``https://www.zjzs.net/art/2026/6/26/art_45_12452.html``
* 附件：``浙江省2026年普通高校招生成绩分数段表(总分).pdf``（文本层可抽取）

官方口径（PDF 正文）
--------------------
表头为「总分 / 人数 / 累计人数」；``人数`` 即本项目 ``count_at_score``，
``累计人数`` 即 ``cumulative_rank``（**数值越小越靠前**，与全系统口径一致）。
最高分段写作「693↑」（693 分及以上合计），解析为 ``score=693`` 且其 ``cumulative_rank``
就是该行累计值。

用法::

    python scripts/collect_zj_score_segment.py fetch --year 2026
    python scripts/collect_zj_score_segment.py parse --year 2026 --pdf <路径>
    python scripts/collect_zj_score_segment.py report --year 2026
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "zhejiang"
OUT_DIR = ROOT / "data" / "normalized" / "zhejiang"
MANIFEST = RAW_DIR / "manifest.json"

#: 2026 年官方附件（文章页 art_45_12452）——来源与 sha256 一并登记进 manifest.json
SOURCE_2026 = {
    "article_url": "https://www.zjzs.net/art/2026/6/26/art_45_12452.html",
    "url": (
        "https://www.zjzs.net/module/download/downfile.jsp?classid=0"
        "&showname=%E6%B5%99%E6%B1%9F%E7%9C%812026%E5%B9%B4%E6%99%AE%E9%80%9A%E9%AB%98%E6%A0%A1"
        "%E6%8B%9B%E7%94%9F%E6%88%90%E7%BB%A9%E5%88%86%E6%95%B0%E6%AE%B5%E8%A1%A8(%E6%80%BB%E5%88%86).pdf"
        "&filename=2af4db3ba885492fa7a607469eb75800.pdf"
    ),
    "out_name": "浙江省2026年普通高校招生成绩分数段表(总分).pdf",
    "note": "浙江省教育考试院 2026-06-26 原文附件（成绩分数段表·总分）",
}

UA = "exam-select-research/0.1 (non-commercial academic use; contact: local)"

#: 行格式：``692 55 447`` 或首行 ``693↑ 392``（693 分及以上，该行为"及以上合计"）
ROW = re.compile(r"^\s*(\d{3})\s*[↑\u2191]?\s+(\d+)\s+(\d+)\s*$")
#: 合成行（最高分段）：``693↑ 392`` —— 只有"分数 + 及以上合计"，没有单独的本段人数
TOP_ROW = re.compile(r"^\s*(\d{3})\s*[↑\u2191]\s+(\d+)\s*$")
HEADER = re.compile(r"^\s*总分\s+人数\s+累计人数\s*$")
TITLE = re.compile(r"成绩分数段表")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, *, timeout: float = 120.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def cmd_fetch(args: argparse.Namespace) -> int:
    if args.year != 2026:
        print(f"✗ 暂无 {args.year} 年官方分数段表的下载地址（只登记了已核实的 2026 年原文）")
        return 2
    spec = SOURCE_2026
    status, body = fetch(args.url or spec["url"])
    print(f"GET 附件 → {status}  {len(body)} bytes")
    if status != 200 or body[:4] != b"%PDF":
        print("✗ 未取到 PDF")
        return 1
    target_dir = RAW_DIR / str(args.year)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / spec["out_name"]
    target.write_bytes(body)
    digest = sha256_bytes(body)
    print(f"→ {target.relative_to(ROOT)}  sha256={digest}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    files = manifest.setdefault(str(args.year), {}).setdefault("files", [])
    files[:] = [f for f in files if f.get("file") != str(target.relative_to(ROOT)).replace("\\", "/")]
    files.append(
        {
            "file": str(target.relative_to(ROOT)).replace("\\", "/"),
            "sha256": digest,
            "bytes": len(body),
            "source_url": args.url or spec["url"],
            "article_url": spec["article_url"],
            "note": spec["note"],
            "retrieved_at": time.strftime("%Y-%m-%d %H:%M"),
        }
    )
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("manifest 已更新")
    return 0


def parse_pdf(path: Path) -> tuple[list[dict], list[str]]:
    """抽取分数段表 → ``[{"score","count_at_score","cumulative_rank"}]``（按分数降序）。"""
    from pypdf import PdfReader

    rows: list[dict] = []
    problems: list[str] = []
    seen: dict[int, dict] = {}
    previous_cumulative = 0
    for page_no, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = page.extract_text() or ""
        if not TITLE.search(text):
            problems.append(f"第 {page_no} 页没有标题，跳过")
            continue
        for line in text.splitlines():
            if HEADER.match(line) or not line.strip():
                continue
            top = TOP_ROW.match(line)
            if top:
                # 「693↑ 392」= 693 分及以上共 392 人：本段人数 = 该合计 − 上一累计
                score, cumulative = int(top.group(1)), int(top.group(2))
                if score in seen:
                    problems.append(f"分数 {score} 重复出现（第 {page_no} 页）")
                    continue
                seen[score] = {
                    "score": score,
                    "count_at_score": cumulative - previous_cumulative,
                    "cumulative_rank": cumulative,
                }
                rows.append(seen[score])
                previous_cumulative = cumulative
                continue
            match = ROW.match(line)
            if not match:
                if re.match(r"^\s*\d{3}", line):
                    problems.append(f"第 {page_no} 页无法解析：{line.strip()[:40]}")
                continue
            score, count, cumulative = (int(match.group(i)) for i in (1, 2, 3))
            if score in seen:
                problems.append(f"分数 {score} 重复出现（第 {page_no} 页）")
                continue
            seen[score] = {
                "score": score,
                "count_at_score": count,
                "cumulative_rank": cumulative,
            }
            rows.append(seen[score])
            previous_cumulative = cumulative
    rows.sort(key=lambda r: -r["score"])
    return rows, problems


def _verify(rows: list[dict]) -> list[str]:
    """自检：累计位次必须等于上一行累计 + 本行人数（与 validate.py 的口径一致）。"""
    problems: list[str] = []
    previous = 0
    for row in rows:
        if row["cumulative_rank"] != previous + row["count_at_score"]:
            problems.append(
                f"score={row['score']}: cumulative={row['cumulative_rank']} "
                f"!= {previous}+{row['count_at_score']}"
            )
        previous = row["cumulative_rank"]
    return problems


def cmd_parse(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf) if args.pdf else (RAW_DIR / str(args.year) / SOURCE_2026["out_name"])
    if not pdf.exists():
        print(f"✗ 找不到 {pdf}（先跑 fetch）")
        return 1
    rows, problems = parse_pdf(pdf)
    if not rows:
        print("✗ 未解析出任何行")
        for problem in problems[:10]:
            print("   ", problem)
        return 1
    problems += _verify(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"zhejiang_score_segment_{args.year}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["year", "score", "count_at_score", "cumulative_rank"]
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({"year": args.year, **row})

    print(f"分数段表：{len(rows)} 行")
    print(f"  分数区间 {rows[0]['score']} – {rows[-1]['score']}")
    print(f"  最高分累计 {rows[0]['cumulative_rank']} · 最低分累计 {rows[-1]['cumulative_rank']}")
    for line in ("一段线 494", "二段线 490"):
        score = int(line.split()[1])
        hit = next((r for r in rows if r["score"] == score), None)
        print(f"  {line} → 累计人数 {hit['cumulative_rank'] if hit else '缺失'}")
    print(f"  解析问题 {len(problems)} 条")
    for problem in problems[:5]:
        print("    -", problem)
    print(f"→ {out.relative_to(ROOT)}")
    (OUT_DIR / f"score_segment_report_{args.year}.json").write_text(
        json.dumps(
            {
                "year": args.year,
                "pdf": pdf.name,
                "sha256": sha256_file(pdf),
                "rows": len(rows),
                "score_min": rows[-1]["score"],
                "score_max": rows[0]["score"],
                "total_candidates": rows[-1]["cumulative_rank"],
                "problems": problems[:50],
                "problem_count": len(problems),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if not problems else 0


def cmd_report(args: argparse.Namespace) -> int:
    path = OUT_DIR / f"zhejiang_score_segment_{args.year}.csv"
    if not path.exists():
        print(f"✗ 找不到 {path}")
        return 1
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    print(f"{path.name}: {len(rows)} 行")
    for row in rows[:3] + rows[-3:]:
        print(f"  {row['score']} 分：本段 {row['count_at_score']} 人，累计 {row['cumulative_rank']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="浙江成绩分数段表采集与规范化（M6）")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_cmd = sub.add_parser("fetch", help="下载官方 PDF 并登记 manifest")
    fetch_cmd.add_argument("--year", type=int, default=2026)
    fetch_cmd.add_argument("--url", default="")
    fetch_cmd.set_defaults(func=cmd_fetch)

    parse_cmd = sub.add_parser("parse", help="PDF → 规范化 CSV")
    parse_cmd.add_argument("--year", type=int, default=2026)
    parse_cmd.add_argument("--pdf", default="")
    parse_cmd.set_defaults(func=cmd_parse)

    report_cmd = sub.add_parser("report", help="打印已解析结果")
    report_cmd.add_argument("--year", type=int, default=2026)
    report_cmd.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
