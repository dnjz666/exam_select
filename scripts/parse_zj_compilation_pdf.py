"""解析浙江省教育考试院《普通高校招生投档及专业录取情况》合编 PDF → 规范化 CSV。

为什么解析合编而不是只找年度 .xls
--------------------------------
1. 合编是**官方原始出版物**（浙江省教育考试院编），分省只是"院校所在地"分组，
   整本都是**浙江考生**的投档数据 → 一本 = 全部浙江投档表；
2. 它比年度一段表**多**：选考科目范围要求、录取人数（=执行计划数）、学制、平均分、
   **一段与二段各自的投档最低分与位次**；
3. 2023/2024/2025 三本可直接抽取文本（2022 那本是扫描件，需 OCR，本脚本不处理）。

官方口径（2024 合编《考生须知》原文，逐条落码）
--------------------------------------------
- 「录取人数」（即执行计划数）→ 本项目的 ``plan_count``
- 「选考科目范围要求」中 ``/`` = 选考其中一门即可（any_of）；``&`` = 均须选考（all_of）
- 「最低分」与「位次」= 该专业投档考生的最低总分（**即专业投档分数线**）及对应位次
- 「某段有最低分但位次栏无数据的，表示该学校专业该段投档人数未满」→ ``MISSING_RANK``
- 「一段或二段无数据的，说明该专业在该段无投档」→ 该段留空
- 「各段均无数据的…通过扩大比例征求志愿录取」→ ``COLLECTED``
- 「院校所在地以标注主校区为主」→ 只当作参考，不当作精确校区

输出列（一行 = 一个院校专业的双段情况，不丢信息）
------------------------------------------------
``year, college_code, college_name, college_province, college_city, major_name,
subject_requirement, subject_mode, plan_count, duration, avg_score,
seg1_min_score, seg1_min_rank, seg2_min_score, seg2_min_rank, data_quality,
seg1_status, seg2_status, source_page``

用法::

    python scripts/parse_zj_compilation_pdf.py --year 2024
    python scripts/parse_zj_compilation_pdf.py --year 2024 --verify-against data/raw/zhejiang/2024/xxx.xls
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import xlrd
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "zhejiang"
OUT = ROOT / "data" / "normalized" / "zhejiang"

SUBJECTS = ("物理", "化学", "生物", "思想政治", "历史", "地理", "技术")
_SUBJECT_ALT = "|".join(SUBJECTS)

#: 院校行（2023 版式）：「0003 浙江工业大学( 浙江·杭州)」整行
COLLEGE_LINE_INLINE = re.compile(r"^\s*(\d{4})\s+(.+?)\s*[（(]\s*([^)）]{1,12}?)\s*[)）]\s*$")
#: 院校代号单独一行（2024/2025 版式）
COLLEGE_CODE_ONLY = re.compile(r"^\s*(\d{4})\s*$")
#: 院校名+所在地单独一行（2024/2025 版式）
COLLEGE_NAME_ONLY = re.compile(r"^\s*(.+?)\s*[（(]\s*([^)）]{1,12}?)\s*[)）]\s*$")
#: 省份分组标记「[ 浙江]」
PROVINCE_MARKER = re.compile(r"^\s*\[\s*([^\]]{1,8}?)\s*\]\s*$")

#: 专业行：缩进 + 专业名 + 选考要求 + 一串数字
MAJOR_LINE = re.compile(
    rf"^[\u3000\s]+(?P<major>.+?)\s+"
    rf"(?P<req>不限|(?:{_SUBJECT_ALT})(?:\s*[/&]\s*(?:{_SUBJECT_ALT}))*)"
    rf"\s+(?P<nums>\d+(?:\s+\d+)*)$"
)

#: 平行投档章节标题（用于定位解析起点；该章节按目录是全书最后一节，故一路解析到底）
PARALLEL_TITLE = re.compile(r"普通类平行投档\s*$|普通类平行投档一、二段各专业录取情况")
LOCATION = re.compile(r"^\s*([^·•・]{1,6})\s*[·•・]\s*([^·•・]{1,10})\s*$")

VALID_DURATION = {2, 3, 4, 5, 6, 8}

#: 全角 → 半角。★ 2025 版整本书用**全角数字**（``４９０``），不做归一化会一条都解析不出来。
_FULLWIDTH = str.maketrans(
    {
        **{chr(0xFF10 + i): str(i) for i in range(10)},
        "（": "(",
        "）": ")",
        "／": "/",
        "＆": "&",
        "．": ".",
        "，": ",",
        "：": ":",
        "；": ";",
        "　": " ",
    }
)


def normalize_text(text: str) -> str:
    """全角转半角（2025 版全书全角，必须处理）。"""
    return text.translate(_FULLWIDTH)


#: 普通类分段线：「普通类 第一段 第二段 / 分数线 490 268」
SEGMENT_LINE = re.compile(r"分数线\s+(\d{3})\s+(\d{3})")


def extract_segment_lines(pages: list[str]) -> tuple[int, int]:
    """从分段线页取普通类一段/二段线。

    这个值不只是展示用——它是**消歧位次与分数的关键**：
    「某段有最低分但位次栏无数据 = 该段投档人数未满」，而投档分恰好等于段线就是这种情形。
    """
    for text in pages[:12]:
        if "普通类" in text and "第一段" in text:
            match = SEGMENT_LINE.search(text)
            if match:
                return int(match.group(1)), int(match.group(2))
    return 0, 0


def parse_subject_requirement(raw: str) -> tuple[str, str]:
    """``物理 / 化学`` → (``any_of``, ``物理,化学``)；``不限`` → (``none``, ````)。"""
    text = raw.strip()
    if text == "不限":
        return "none", ""
    if "&" in text:
        subjects = [part.strip() for part in text.split("&")]
        return "all_of", ",".join(subjects)
    if "/" in text:
        subjects = [part.strip() for part in text.split("/")]
        return "any_of", ",".join(subjects)
    return "all_of", text


def _split_location(raw: str) -> tuple[str, str]:
    """``浙江·杭州`` → (``浙江``, ``杭州``)；``北京`` → (``北京``, ``北京``)。"""
    match = LOCATION.match(raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return raw.strip(), ""


def _looks_like_rank(token: str) -> bool:
    """判断一个数字串更像是「位次」而不是「分数」。

    ★ 书里位次与分数的**位数都不固定**：
      * 2024 版位次 ``4221``（4 位）、分数 ``672``（3 位）；
      * 2023 提前批位次写成 ``000106``（补零到 6 位）；
      * 顶尖院校位次可以小到 ``2``（北京大学工商管理类）。

    因此只看长度必然出错。三条判据：
      1. **有前导零** → 位次（分数不会写成 0672）；
      2. **数值 > 750** → 位次（高考总分上限 750）；
      3. **数值 < 200** → 位次（普通类投档分不可能低于 200）。
    """
    if token.startswith("0") and len(token) > 1:
        return True
    value = int(token)
    return value > 750 or value < 200


def _split_tail(
    nums: list[str], seg1_line: int = 0
) -> tuple[int, int, int, list[tuple[int, int | None]], int]:
    """把数字串拆成 ``(录取人数, 学制, 平均分, [(分数, 位次|null), ...], 可疑数)``。

    结构固定为 ``录取人数 学制 平均分 [一段分 [一段位次]] [二段分 [二段位次]]``。

    **难点**：书里位次与分数的位数都不固定，而且顶尖院校的位次可以落在分数区间里
    （北京大学工商管理类位次 = 2；浙江大学竺可桢班 694/位次 639）。仅靠值域无法区分，
    因此引入一条官方语义作为消歧依据：

    > 某段有最低分但位次栏无数据的，表示该学校专业该段投档人数未满。

    即 **一段投档分恰好等于一段线 → 该段未满，后面那个数字是二段分而不是位次**；
    反之，一段分高于段线（尤其 600+ 的专业不可能招不满）→ 后面那个数字是该段的位次。
    """
    count, duration, avg = (int(nums[0]), int(nums[1]), int(nums[2]))
    groups: list[tuple[int, int | None]] = []
    suspicious = 0
    tail = nums[3:]
    for position, token in enumerate(tail):
        remaining = len(tail) - position - 1
        last = groups[-1] if groups else None
        if last is not None and last[1] is None:
            if _looks_like_rank(token) or (
                last[0] != seg1_line and remaining == 0 and 200 <= int(token) <= 750
            ):
                groups[-1] = (last[0], int(token))
                continue
        value = int(token)
        if 200 <= value <= 750:
            groups.append((value, None))
            continue
        suspicious += 1
    return count, duration, avg, groups, suspicious


def _segment_status(score: int | None, rank: int | None) -> str:
    if score is None:
        return "NO_ADMISSION"  # 该段无投档
    if rank is None:
        return "NOT_FULL"  # 有最低分但位次空 = 该段投档人数未满
    return "OK"


def parse_pdf(pdf: Path, year: int) -> tuple[list[dict], list[str], dict]:
    reader = PdfReader(str(pdf))
    pages = []
    for page in reader.pages:
        try:
            pages.append(normalize_text(page.extract_text() or ""))
        except Exception:  # noqa: BLE001
            pages.append("")

    seg1_line, seg2_line = extract_segment_lines(pages)
    start = next(
        (index for index, text in enumerate(pages) if "普通类平行投档" in text and index > 3), None
    )
    if start is None:
        return [], ["没有找到「普通类平行投档」章节"], {}

    rows: list[dict] = []
    problems: list[str] = []
    current_college: dict | None = None
    current_province = ""
    pending_code = ""
    stats = Counter()

    for index in range(start, len(pages)):
        for raw_line in pages[index].splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                continue

            marker = PROVINCE_MARKER.match(line)
            if marker:
                current_province = marker.group(1).strip()
                continue

            # 版式 A：代号与校名同一行
            college = COLLEGE_LINE_INLINE.match(line)
            if college:
                code, name, location = college.groups()
                province, city = _split_location(location)
                current_college = {
                    "college_code": code,
                    "college_name": name.replace(" ", ""),
                    "college_province": province or current_province,
                    "college_city": city,
                }
                pending_code = ""
                stats["colleges"] += 1
                continue

            # 版式 B 第 1 步：代号单独一行
            code_only = COLLEGE_CODE_ONLY.match(line)
            if code_only:
                pending_code = code_only.group(1)
                continue

            # 版式 B 第 2 步：校名+所在地单独一行（必须紧跟代号，否则可能是别的括注行）
            if pending_code:
                name_only = COLLEGE_NAME_ONLY.match(line)
                if name_only:
                    name, location = name_only.groups()
                    province, city = _split_location(location)
                    current_college = {
                        "college_code": pending_code,
                        "college_name": name.replace(" ", ""),
                        "college_province": province or current_province,
                        "college_city": city,
                    }
                    pending_code = ""
                    stats["colleges"] += 1
                    continue

            major = MAJOR_LINE.match(line)
            if major:
                if current_college is None:
                    problems.append(f"p{index + 1}: 专业行出现在院校行之前：{line.strip()[:40]}")
                    stats["orphan"] += 1
                    continue
                nums = major.group("nums").split()
                if len(nums) < 3:
                    problems.append(f"p{index + 1}: 数字列不足：{line.strip()[:50]}")
                    continue
                try:
                    count, duration, avg, groups, suspicious = _split_tail(nums, seg1_line)
                except (ValueError, IndexError) as exc:
                    problems.append(f"p{index + 1}: 数字解析失败（{exc}）：{line.strip()[:50]}")
                    continue
                if suspicious:
                    stats["suspicious_segment"] += suspicious

                if duration not in VALID_DURATION or not (1 <= count <= 3000) or not (200 <= avg <= 750):
                    problems.append(
                        f"p{index + 1}: 字段越界（人数{count}/学制{duration}/平均分{avg}）："
                        f"{line.strip()[:50]}"
                    )
                    stats["out_of_range"] += 1
                    continue

                seg1 = groups[0] if len(groups) > 0 else (None, None)
                seg2 = groups[1] if len(groups) > 1 else (None, None)
                if len(groups) > 2:
                    problems.append(f"p{index + 1}: 出现第三段数据：{line.strip()[:50]}")
                    stats["extra_segment"] += 1

                mode, subjects = parse_subject_requirement(major.group("req"))
                seg1_status = _segment_status(*seg1)
                seg2_status = _segment_status(*seg2)
                if seg1_status == "NO_ADMISSION" and seg2_status == "NO_ADMISSION":
                    quality = "COLLECTED"  # 各段均无数据 → 征求志愿录取
                elif seg1_status == "NOT_FULL" or seg2_status == "NOT_FULL":
                    quality = "MISSING_RANK"
                else:
                    quality = "OK"

                rows.append(
                    {
                        "year": year,
                        **current_college,
                        "major_name": major.group("major").strip(),
                        "subject_requirement": major.group("req").replace(" ", ""),
                        "subject_mode": mode,
                        "subject_subjects": subjects,
                        "plan_count": count,
                        "duration": duration,
                        "avg_score": avg,
                        "seg1_min_score": seg1[0],
                        "seg1_min_rank": seg1[1],
                        "seg2_min_score": seg2[0],
                        "seg2_min_rank": seg2[1],
                        "data_quality": quality,
                        "seg1_status": seg1_status,
                        "seg2_status": seg2_status,
                        "source_page": index + 1,
                    }
                )
                stats[quality] += 1
    stats["seg1_line"] = seg1_line
    stats["seg2_line"] = seg2_line
    return rows, problems, dict(stats)


FIELDS = [
    "year",
    "college_code",
    "college_name",
    "college_province",
    "college_city",
    "major_name",
    "subject_requirement",
    "subject_mode",
    "subject_subjects",
    "plan_count",
    "duration",
    "avg_score",
    "seg1_min_score",
    "seg1_min_rank",
    "seg2_min_score",
    "seg2_min_rank",
    "data_quality",
    "seg1_status",
    "seg2_status",
    "source_page",
]


def _norm_key(text: str) -> str:
    """比对用的名字归一：统一全/半角括号与空白。

    .xls 写「（含涉外法治双学士学位项目）」，PDF 写「( 含涉外法治双学士学位项目)」——
    不归一会把同一个专业当成两个，校验率会凭空掉一截。
    """
    table = str.maketrans({"（": "(", "）": ")", "，": ",", "、": ",", "·": "", "•": ""})
    return re.sub(r"[\s\u3000]", "", text.translate(table))


def verify_against_xls(rows: list[dict], xls: Path) -> str:
    """拿年度一段表 .xls 交叉校验（独立来源 → 能真正发现解析错误）。

    两边都按 ``(院校名, 专业名)`` 建**多重集**：浙江录取里同一院校同一专业名
    可能对应多个专业代号（不同校区/方向），用 dict 会互相覆盖，制造假不一致。
    """
    sheet = xlrd.open_workbook(xls).sheet_by_index(0)
    expected: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for index in range(1, sheet.nrows):
        code = re.sub(r"\D", "", str(sheet.cell_value(index, 0))).zfill(4)
        if not code.strip("0"):
            continue
        name = _norm_key(str(sheet.cell_value(index, 1)))
        major = _norm_key(str(sheet.cell_value(index, 3)))
        score_raw = str(sheet.cell_value(index, 5)).strip()
        rank_raw = str(sheet.cell_value(index, 6)).strip()
        if not name or not major:
            continue
        expected.setdefault((name, major), []).append(
            (
                int(float(score_raw)) if score_raw else -1,
                int(float(rank_raw)) if rank_raw else -1,
            )
        )

    parsed: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in rows:
        if row["seg1_status"] == "NO_ADMISSION":
            continue
        key = (_norm_key(row["college_name"]), _norm_key(row["major_name"]))
        parsed.setdefault(key, []).append((row["seg1_min_score"] or -1, row["seg1_min_rank"] or -1))

    shared = [key for key in expected if key in parsed]
    # 只比对多重集完全一致的键（重复键无法一一对应，单独统计）
    unique_keys = [key for key in shared if len(expected[key]) == 1 and len(parsed[key]) == 1]
    agree = sum(1 for key in unique_keys if expected[key] == parsed[key])
    mismatch = [
        f"{key[0]}·{key[1]}：xls={expected[key][0]} pdf={parsed[key][0]}"
        for key in unique_keys
        if expected[key] != parsed[key]
    ]
    dup_keys = len(shared) - len(unique_keys)

    lines = [
        "交叉校验（合编 PDF 解析 vs 年度一段表 .xls，同一年的两个独立官方来源）",
        f"  .xls 记录数            : {sum(len(v) for v in expected.values())}",
        f"  PDF 一段记录数         : {sum(len(v) for v in parsed.values())}",
        f"  两边都有的键           : {len(shared)}（其中重复键 {dup_keys} 个，不参与逐一比对）",
        f"  可逐一比对的键         : {len(unique_keys)}",
        f"  分数与位次完全一致     : {agree}"
        + (f"（{agree / len(unique_keys):.2%}）" if unique_keys else ""),
    ]
    if mismatch:
        lines.append(f"  不一致 {len(mismatch)} 条，样例（最多 10 条）：")
        lines.extend(f"    - {item}" for item in mismatch[:10])
    only_xls = [key for key in expected if key not in parsed][:5]
    if only_xls:
        lines.append(f"  仅 .xls 有（样例）：{only_xls}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="解析浙江合编 PDF → 规范化 CSV")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--pdf", default="")
    parser.add_argument("--verify-against", default="")
    args = parser.parse_args(argv)

    pdf = Path(args.pdf) if args.pdf else next(RAW.joinpath(str(args.year)).glob("*.pdf"))
    print(f"解析：{pdf.name}")
    rows, problems, stats = parse_pdf(pdf, args.year)
    if not rows:
        print("没有解析出任何记录")
        for problem in problems[:20]:
            print("  ", problem)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"zhejiang_parallel_compilation_{args.year}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  分段线：一段 {stats.get('seg1_line')} · 二段 {stats.get('seg2_line')}（取自书内《各类别分段线》）")
    print(f"  记录数 {len(rows)} · 院校 {len({row['college_code'] for row in rows})} 所")
    print(f"  数据质量分布：{ {k: v for k, v in stats.items() if k in ('OK', 'MISSING_RANK', 'COLLECTED')} }")
    print(f"  选考模式分布：{dict(Counter(row['subject_mode'] for row in rows))}")
    print(f"  段情况：一段 {dict(Counter(row['seg1_status'] for row in rows))} · "
          f"二段 {dict(Counter(row['seg2_status'] for row in rows))}")
    print(f"  解析问题 {len(problems)} 条" + (f"（前 5 条）" if problems else ""))
    for problem in problems[:5]:
        print("    -", problem)
    print(f"→ {out.relative_to(ROOT)}")

    if args.verify_against:
        print()
        print(verify_against_xls(rows, Path(args.verify_against)))

    (OUT / f"parse_report_{args.year}.json").write_text(
        json.dumps(
            {"year": args.year, "pdf": pdf.name, "records": len(rows), "stats": stats,
             "problems": problems[:50], "problem_count": len(problems)},
            ensure_ascii=False, indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
