"""从官方合编 PDF 中抽取院校清单（按所在地分组）。

合编 PDF 的正文结构是「院校代码 + 院校名(省·市) + 各专业一行」。
本脚本只抽**院校行**，产出 ``(college_code, college_name, province, city)`` 清单，
用于：
1. 确定"浙江省内院校"的范围（寝室/校园环境采集的优先批次）；
2. M6 入库时把院校与所在地对上（本项目的 ``colleges`` 表需要 city/province）。

⚠️ 只做清单抽取，不做专业行解析——那是 M6 的工作。

用法::

    python scripts/collect_pdf_colleges.py --pdf <合编.pdf> --year 2023 --province 浙江 --out <csv>
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent

#: 「0003 浙江工业大学( 浙江·杭州)」；括号内的空格、间隔号写法不统一，全部容忍
COLLEGE_LINE = re.compile(
    r"^\s*(\d{4})\s+([^\s(（]+(?:[^\s(（]*))\s*[（(]\s*([^·•・]{1,6})\s*[·•・]\s*([^)）]{1,10})\s*[)）]\s*$"
)


def extract(pdf: Path, province: str | None) -> list[dict[str, str]]:
    reader = PdfReader(str(pdf))
    found: dict[tuple[str, str], dict[str, str]] = {}
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 - 单页损坏不该中断整本抽取
            continue
        for raw_line in text.splitlines():
            match = COLLEGE_LINE.match(raw_line.strip())
            if not match:
                continue
            code, name, prov, city = match.groups()
            name = name.strip().replace(" ", "")
            prov, city = prov.strip(), city.strip()
            if province and prov != province:
                continue
            found[(code, name)] = {
                "college_code": code,
                "college_name": name,
                "province": prov,
                "city": city,
                "source_page": str(index + 1),
            }
    return sorted(found.values(), key=lambda item: item["college_code"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从官方合编 PDF 抽取院校清单")
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--province", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    rows = extract(Path(args.pdf), args.province or None)
    if not rows:
        print("没有抽到院校行——检查 PDF 是否为扫描件，或正则是否匹配")
        return 1

    out = Path(args.out) if args.out else ROOT / "data" / "normalized" / "zhejiang" / (
        f"colleges_{args.year}{'_' + args.province if args.province else ''}.csv"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["college_code", "college_name", "province", "city", "source_page"]
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"{args.year}{('/' + args.province) if args.province else ''}：{len(rows)} 所院校")
    print("城市分布:", dict(collections.Counter(row["city"] for row in rows).most_common()))
    print(f"→ {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
