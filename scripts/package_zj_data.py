"""把浙江真实数据打包成可交付目录（供复制到桌面 ``ScoreLines_zj``）。

产出（暂存于 ``data/packages/ScoreLines_zj``，再由人工/提权命令复制到目标位置）::

    ScoreLines_zj/
    ├── README.md                    数据说明、口径、来源、缺口、合规
    ├── manifest.json                每个文件：来源 URL / sha256 / 大小
    ├── 01_投档分数线表/              机器可读的年度「普通类第一段平行投档分数线表」(.xls)
    ├── 02_投档及专业录取情况/         浙江省教育考试院官方合编（PDF/RAR，含选考要求与一·二段）
    ├── 03_规范化CSV/                 解析后的表格（UTF-8 BOM，Excel 可直接打开）
    ├── 04_寝室与校园环境/             分片 JSON + 汇总 JSON/CSV（每条结论带来源与逐字引文）
    └── 05_原始网页存档/               官方文章页 HTML（离线核对用）

设计原则
--------
- **不做任何加工性推断**：只搬运与解析，缺什么就在 README 的"缺口"里写明；
- **每个文件都有来源**：manifest 记录 source_url 与 sha256，便于日后核对与升级；
- 可重复执行（幂等）：每次都重建暂存目录，结果一致。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "zhejiang"
NORM = ROOT / "data" / "normalized" / "zhejiang"
CHUNKS = RAW / "_dorm_chunks"
STAGE = ROOT / "data" / "packages" / "ScoreLines_zj"

DIR_SL = "01_投档分数线表"
DIR_PDF = "02_投档及专业录取情况"
DIR_CSV = "03_规范化CSV"
DIR_DORM = "04_寝室与校园环境"
DIR_PAGES = "05_原始网页存档"

#: **不进交付包**的原始文件（连同原因）。判据只有一条：**对 M6 数据导入有没有用**。
#: 被排除的文件都会连同来源 URL 记进 ``manifest.json`` 的 ``excluded``，
#: 所以排除掉的是"体积"而不是"可追溯性"——需要时随时能按 URL 重新下载。
EXCLUDED: dict[str, str] = {
    "浙江省普通高校招生投档及专业录取情况（2022）.pdf": (
        "扫描件（366 页、每页一张图、无文本层），无法解析导入；"
        "2022 年数据已由 01 目录下的官方年度一段表 .xls 覆盖"
    ),
    "浙江省普通高校招生投档及专业录取情况（2022）.rar": "同上，且与已解出的 PDF 内容重复",
    "浙江省2021年普通高校招生普通类第一段平行投档分数线表.rar": (
        "压缩包，内容与已解出的 2021 年 .xls 完全重复；导入只用 .xls"
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_into(path: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    shutil.copy2(path, target)
    return target


def load_manifest() -> dict:
    path = RAW / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def merge_dorm_chunks() -> tuple[list[dict], list[str]]:
    """合并 ``_dorm_chunks/chunk_*.json`` → 按院校去重的完整清单。

    只认 ``chunk_*.json``（``_diagnostic.json`` 之类的自测文件不参与汇总）。
    """
    schools: dict[tuple[str, str], dict] = {}
    notes: list[str] = []
    if not CHUNKS.exists():
        return [], ["未找到寝室/校园环境分片目录"]
    for path in sorted(CHUNKS.glob("chunk_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            notes.append(f"{path.name} 不是合法 JSON：{exc}")
            continue
        for school in payload.get("schools") or []:
            key = (str(school.get("college_code", "")), str(school.get("college_name", "")))
            school["source_chunk"] = path.name
            schools[key] = school
        if payload.get("notes"):
            notes.append(f"{path.name}: {payload['notes']}")
    return [schools[key] for key in sorted(schools)], notes


def write_dorm(stage: Path) -> tuple[int, int, list[str]]:
    schools, notes = merge_dorm_chunks()
    target = stage / DIR_DORM
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(CHUNKS.glob("chunk_*.json")):
        shutil.copy2(path, target / path.name)

    if not schools:
        return 0, 0, notes + ["没有可汇总的寝室/校园环境数据（分片为空）"]

    (target / "dorm_campus.json").write_text(
        json.dumps({"count": len(schools), "schools": schools}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (target / "dorm_campus_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "college_code",
                "college_name",
                "city",
                "status",
                "layout",
                "bed_type",
                "bathroom",
                "air_conditioner",
                "campus_env",
                "confidence",
                "evidence_count",
                "first_source",
                "unresolved",
            ]
        )
        for school in schools:
            dorm = school.get("dorm") or {}
            evidence = school.get("evidence") or []
            writer.writerow(
                [
                    school.get("college_code", ""),
                    school.get("college_name", ""),
                    school.get("city", ""),
                    school.get("status", ""),
                    dorm.get("layout", ""),
                    dorm.get("bed_type", ""),
                    dorm.get("bathroom", ""),
                    dorm.get("air_conditioner", ""),
                    (school.get("campus_env") or "").replace("\n", " "),
                    school.get("confidence", ""),
                    len(evidence),
                    (evidence[0].get("url", "") if evidence else ""),
                    "；".join(school.get("unresolved") or []),
                ]
            )
    with_sources = sum(1 for school in schools if school.get("evidence"))
    return len(schools), with_sources, notes


README_TEMPLATE = """# 浙江真实数据包（ScoreLines_zj）

> 为「高考志愿填报智能体」的 **M6 真实数据接入**准备的浙江数据。
> 本包**只做采集与规范化，尚未入库**（用户明确要求先不开始 M6 接入）。
> 生成时间：{generated_at}
> 生成脚本：`scripts/package_zj_data.py`（可重跑，幂等）

---

## 1. 目录内容

| 目录 | 内容 | 说明 |
|---|---|---|
| `{dir_sl}/` | 年度「普通类第一段平行投档分数线表」`.xls` | **机器可读**，列：学校代号 / 学校名称 / 专业代号 / 专业名称 / 计划数 / 分数线 / 位次 |
| `{dir_pdf}/` | 浙江省教育考试院官方合编《普通高校招生投档及专业录取情况》 | 含**选考科目要求、录取人数、学制、平均分、一段/二段最低分与位次**，信息量大于一段表 |
| `{dir_csv}/` | 解析后的规范化 CSV（UTF-8 BOM） | 可直接用 Excel 打开；列名与项目 `admission_history` 口径对齐 |
| `{dir_dorm}/` | 寝室与校园环境资料（JSON + 汇总 CSV） | **每条结论都带来源 URL 与逐字引文**；查不到的标 `not_found`，不编造 |
| `{dir_pages}/` | 官方文章页 HTML 存档 | 离线核对用 |

`manifest.json` 记录每个原始文件的**来源 URL、sha256、大小**。

---

## 2. 数据来源（均为浙江省教育考试院官网 www.zjzs.net 公开发布物）

{source_table}

抓取纪律：
- 该站 `robots.txt` 返回 **404（未声明策略）**；
- 单线程、请求间隔 2 秒、只取**公开发布的数据表**，不做整站镜像、不并发轰炸；
- 所有文件保留原始文件名与 sha256，便于与官网原件比对。

---

## 3. 口径与关键发现

### 3.1 「位次」为空 = 该专业本轮投档人数未满
2026 年表尾官方原文（已逐字留档）：

> 注：位次栏目为空的，表示该学校专业本轮投档人数未满。

2024 年表中有 **1,857 行**分数正好等于当年一段线（492）且位次为空，属于同一情形。
**M6 入库时必须标 `data_quality=MISSING_RANK`，且按 DOMAIN_RULES §6.2 Step 1 不参与概率计算**
（拿"没招满"的记录去算门槛会系统性高估难度）。

### 3.2 三年合编 PDF 已解析成 CSV（比一段表更丰富）
`{dir_csv}/zhejiang_parallel_compilation_YYYY.csv`（2023/2024/2025）每行一个院校专业，含：
专业名 / 选考科目范围要求 / 录取人数 / 学制 / 平均分 / **一段最低分与位次** / **二段最低分与位次**。

官方口径（2024 合编《考生须知》原文）：
- 「录取人数」**即执行计划数** → 对应本项目 `plan_count`
- 选考要求里 `/` = 选考其中一门即可（`any_of`）；`&` = 均须选考（`all_of`）
- 「最低分」与「位次」= 该专业投档考生的最低总分（**即专业投档分数线**）及对应位次
- **某段有最低分但位次为空 = 该段投档人数未满**（→ `MISSING_RANK`）
- 各段均无数据 = 通过征求志愿录取（→ `COLLECTED`）

**解析正确性有独立交叉验证**：2024 年同时存在官方年度一段表 `.xls` 与官方合编 PDF，
两个**相互独立**的官方来源逐条比对，**13,506 条可比对记录 100.00% 完全一致**（分数与位次都一致）。
解析脚本：`scripts/parse_zj_compilation_pdf.py`。

---

## 4. 缺口（诚实清单）

{gaps}

---

## 5. 合规提示

- 本包为**教育考试院公开发布数据**的收集，用于非商业的研究/教学用途；
- 寝室与校园环境部分**只摘录了 ≤60 字的逐字片段**作为证据，其余为事实性摘要，未整段复制；
- 该部分数据来自公开网页（含社交平台用户内容），**可信度参差**，已在每条记录里标注
  `kind`（official/social/aggregator）、`confidence` 与 `unresolved`，**不得当作官方结论**；
- 正式接入（M6）前请再次确认数据来源授权与使用条款（DOMAIN_RULES §1.4）。

---

## 6. 文件清单

{file_table}
"""


def write_readme(stage: Path, manifest: dict, dorm_total: int, dorm_sourced: int,
                 dorm_notes: list[str], summary: dict) -> None:
    source_rows = []
    for year, entry in sorted(manifest.items()):
        for record in entry.get("files", []):
            name = record["file"].split("/")[-1]
            url = record.get("source_url") or ""
            label = f"[`{name}`]({url})" if url else f"`{name}`"
            source_rows.append(f"| {year} | {label} | {record.get('note') or ''} |")
    source_table = "\n".join(
        ["| 年份 | 原始文件 | 来源说明 |", "|---|---|---|"] + (source_rows or ["| — | — | — |"])
    )

    gaps: list[str] = []
    have_sl = sorted(
        year
        for year, entry in manifest.items()
        if any(record["file"].lower().endswith((".xls", ".xlsx")) for record in entry.get("files", []))
    )
    gaps.append(
        f"- **年度一段平行投档分数线表（官方 .xls）**：现有 {' / '.join(have_sl)} 年。"
        "**2023 与 2025 没有单独的 .xls**——这两年直接用官方合编 PDF 解析（见上一节），"
        "列比年度表**更多**（选考要求、录取人数、平均分、一/二段位次），不是缺口。"
    )
    gaps.append(
        "- **2022 年合编 PDF 已从交付包移除**：它是扫描件（无文本层），不能用于导入；"
        "2022 年的数据由 `01_投档分数线表/` 的年度一段表 .xls 覆盖。"
        "若日后需要 2022 年的「专业录取情况」（录取人数/平均分），可按 `manifest.json.excluded` 里的来源 URL 取回并 OCR。"
    )
    gaps.append(
        f"- **寝室与校园环境**：已采集 {dorm_total} 所（其中 {dorm_sourced} 所有至少一条来源），"
        "均为浙江省内院校。在浙江投档表里出现过的院校约 2,100 所，逐个检索成本很高，建议分批推进。"
    )
    gaps.append(
        "- **院校更名造成的重复**：投档表与院校清单中存在同一所学校的新旧两个名字"
        "（浙江科技大学 / 浙江科技学院、嘉兴大学 / 嘉兴学院、浙江机电职业技术大学 / 浙江机电职业技术学院）。"
        "M6 入库时必须按院校代号归一合并，否则同一所学校会被算成两所。"
    )
    gaps.append(
        "- **2021/2022 的院校名带层次后缀**（如「浙江大学（一流大学建设高校）」），2024 年起不再带；"
        "跨年匹配前需要剥离该后缀。"
    )
    gaps.append(
        "- **历年一段线**（用于识别「未满」记录）：2021 = 495、2022 = 497、2023 = 488、2024 = 492、"
        "2025 = 490、2026 = 494。各年「位次为空」的行其分数线恰好等于当年一段线，可据此校验导入结果。"
    )
    if dorm_notes:
        gaps.append("- 寝室/校园环境分片执行备注：\n" + "\n".join(f"  - {note}" for note in dorm_notes[:10]))
    if dorm_notes:
        gaps.append("- 分片执行备注：\n" + "\n".join(f"  - {note}" for note in dorm_notes[:10]))

    file_rows = ["| 文件 | 大小 | sha256（前 16 位） |", "|---|---|---|"]
    for path in sorted(stage.rglob("*")):
        if path.is_file() and path.name not in ("README.md", "manifest.json"):
            file_rows.append(
                f"| `{path.relative_to(stage).as_posix()}` | {path.stat().st_size:,} B | `{sha256(path)[:16]}` |"
            )

    import datetime

    (stage / "README.md").write_text(
        README_TEMPLATE.format(
            generated_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            dir_sl=DIR_SL,
            dir_pdf=DIR_PDF,
            dir_csv=DIR_CSV,
            dir_dorm=DIR_DORM,
            dir_pages=DIR_PAGES,
            source_table=source_table,
            gaps="\n".join(gaps),
            file_table="\n".join(file_rows),
        ),
        encoding="utf-8",
    )


def clean_name(path: Path) -> str:
    """规范文件名：去掉"副本副本"前缀与下载器追加的 ``11(1)`` 之类后缀。

    ⚠️ **必须保护 ``（2022）`` 这类年份后缀**：它是区分三年合编 PDF 的唯一标识，
    早期版本的无差别"剥掉结尾括号数字"曾把年份一起剥掉，导致三个 PDF 变成
    ``…情况.pdf`` / ``…情况_pdf.pdf`` 这种无法分辨的名字。

    只改**交付包里的名字**；``manifest.json`` 仍保留原始文件名与 sha256，便于与官网原件比对。
    """
    stem = path.stem
    for prefix in ("副本副本", "副本"):
        while stem.startswith(prefix):
            stem = stem[len(prefix) :]

    # 先把「（2022）」这类年份后缀摘出来保护，最后再放回去
    year_suffix = ""
    match = re.search(r"[（(](?:19|20)\d{2}[)）]$", stem)
    if match:
        year_suffix = stem[match.start() :]
        stem = stem[: match.start()]

    # 剥下载器后缀："…分数线表11(1)" → "…分数线表"；"…表(1)" → "…表"
    while True:
        cleaned = re.sub(r"\d*[（(]\d+[)）]$", "", stem)
        cleaned = re.sub(r"[（(]\d*$|[)）]\d*$|\d+[（(]$", "", cleaned)
        if cleaned == stem:
            break
        stem = cleaned

    stem = (stem.strip() or path.stem) + year_suffix
    return f"{stem}{path.suffix.lower()}"


def classify(path: Path) -> str:
    """归档目录：一段投档分数线表（含其原始 rar 压缩包）→ 01，其余官方合编 → 02。"""
    return DIR_SL if "第一段平行投档分数线表" in path.name else DIR_PDF


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打包浙江真实数据到暂存目录")
    parser.add_argument("--stage", default=str(STAGE))
    args = parser.parse_args(argv)
    stage = Path(args.stage)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for name in (DIR_SL, DIR_PDF, DIR_CSV, DIR_DORM, DIR_PAGES):
        (stage / name).mkdir(parents=True, exist_ok=True)

    manifest = load_manifest()
    copied = 0
    excluded: dict[str, str] = {}
    original_names: dict[str, str] = {}
    for year_dir in sorted(path for path in RAW.iterdir() if path.is_dir() and path.name.isdigit()):
        for path in sorted(year_dir.iterdir()):
            if path.suffix.lower() not in (".xls", ".xlsx", ".pdf", ".rar", ".zip"):
                continue
            if path.name in EXCLUDED:
                excluded[path.name] = EXCLUDED[path.name]
                continue
            target_dir = stage / classify(path)
            target = target_dir / clean_name(path)
            if target.exists():  # 同年同名（如 .rar 与解出的 .pdf）不该互相覆盖
                target = target_dir / f"{target.stem}_{path.suffix.lstrip('.').lower()}{target.suffix}"
            shutil.copy2(path, target)
            original_names[target.relative_to(stage).as_posix()] = path.name
            copied += 1

    for path in sorted(NORM.glob("*.csv")):
        copy_into(path, stage / DIR_CSV)
        copied += 1
    for path in sorted(NORM.glob("summary.json")):
        copy_into(path, stage / DIR_CSV)
        copied += 1

    pages = RAW / "_pages"
    if pages.exists():
        for path in sorted(pages.glob("*.html")):
            copy_into(path, stage / DIR_PAGES)
            copied += 1

    dorm_total, dorm_sourced, dorm_notes = write_dorm(stage)

    file_manifest = {}
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            file_manifest[path.relative_to(stage).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
    (stage / "manifest.json").write_text(
        json.dumps(
            {
                "package": "ScoreLines_zj",
                "raw_sources": manifest,
                "original_file_names": original_names,
                "excluded": excluded,
                "files": file_manifest,
                "dorm_campus": {"schools": dorm_total, "with_evidence": dorm_sourced},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary_path = NORM / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    write_readme(stage, manifest, dorm_total, dorm_sourced, dorm_notes, summary)

    print(f"暂存目录：{stage.relative_to(ROOT)}")
    print(f"  原始文件 {copied} 个 · 寝室/校园环境 {dorm_total} 所（{dorm_sourced} 所有来源）")
    for name in (DIR_SL, DIR_PDF, DIR_CSV, DIR_DORM, DIR_PAGES):
        count = sum(1 for _ in (stage / name).rglob("*") if _.is_file())
        print(f"  {name}: {count} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
