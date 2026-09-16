"""zjzs.net（浙江省教育考试院）抓取工具：robots 检查 + 文章页附件提取。

纪律（DOMAIN_RULES §1.4）
------------------------
1. **先看 robots.txt**，不允许的路径一概不抓；
2. 单线程、请求间加延迟，不做并发轰炸——只取公开发布的数据表，不镜像整站；
3. 每个下载物记录来源 URL 与 sha256（做成本项目的 source_url 口径）。

用法::

    python scripts/zjzs_fetch.py robots
    python scripts/zjzs_fetch.py page <文章URL>            # 列出页面里的链接
    python scripts/zjzs_fetch.py download <URL> --year 2021 --out-name 普通类第一段平行投档分数线表.xls
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "zhejiang"
UA = "exam-select-research/0.1 (non-commercial academic use; contact: local)"
DELAY_SECONDS = 2.0

_last_request = 0.0


def fetch(url: str, *, timeout: float = 30.0) -> tuple[int, bytes, dict[str, str]]:
    """取一个 URL（带礼貌延迟）。返回 ``(status, body, headers)``。"""
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < DELAY_SECONDS:
        time.sleep(DELAY_SECONDS - elapsed)
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            _last_request = time.time()
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as exc:
        _last_request = time.time()
        return exc.code, exc.read(), dict(exc.headers or {})


def decode(body: bytes, headers: dict[str, str]) -> str:
    content_type = headers.get("Content-Type", "")
    match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
    for encoding in ([match.group(1)] if match else []) + ["utf-8", "gb18030", "gbk"]:
        try:
            return body.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return body.decode("utf-8", errors="replace")


def cmd_robots(_: argparse.Namespace) -> int:
    status, body, headers = fetch("https://www.zjzs.net/robots.txt")
    print(f"GET /robots.txt → {status}")
    print(decode(body, headers) if body else "(空)")
    return 0


def cmd_page(args: argparse.Namespace) -> int:
    status, body, headers = fetch(args.url)
    print(f"GET {args.url} → {status}  ({len(body)} bytes)")
    if status != 200:
        return 1
    html = decode(body, headers)
    title = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if title:
        print(f"标题：{title.group(1).strip()}")
    # 抽取所有链接，重点标注附件
    links = re.findall(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", html, re.I)
    interesting: list[str] = []
    suffixes = (".xls", ".xlsx", ".pdf", ".doc", ".docx", ".zip", ".rar", ".7z")
    for link in links:
        low = link.lower()
        if any(low.endswith(ext) or ext + "?" in low for ext in suffixes):
            interesting.append(link)
    print(f"\n附件类链接（{len(set(interesting))} 条）：")
    for link in sorted(set(interesting)):
        print(f"  {urllib.parse.urljoin(args.url, link)}")
    if args.all_links:
        print(f"\n全部链接（{len(set(links))} 条）：")
        for link in sorted(set(links))[: args.all_links]:
            print(f"  {urllib.parse.urljoin(args.url, link)}")
    # 保存原文便于离线核对
    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"\n原文已存：{out}")
    return 0


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cmd_download(args: argparse.Namespace) -> int:
    status, body, headers = fetch(args.url, timeout=120.0)
    print(f"GET {args.url} → {status}  ({len(body)} bytes)  {headers.get('Content-Type', '')}")
    if status != 200 or not body:
        return 1
    target_dir = RAW_DIR / str(args.year)
    target_dir.mkdir(parents=True, exist_ok=True)
    name = args.out_name or urllib.parse.unquote(Path(urllib.parse.urlparse(args.url).path).name)
    target = target_dir / name
    target.write_bytes(body)
    digest = _sha256_bytes(body)
    print(f"已保存：{target.relative_to(ROOT)}\nsha256={digest}")

    manifest_path = RAW_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    key = f"{args.year}"
    # ★ 每年可能登记多个文件（年度表 + 合编 PDF + 压缩包），必须**累积**而不是覆盖，
    #   否则 manifest 只剩最后一个文件，"我到底有哪些年的数据"就说不清了。
    entry = manifest.setdefault(key, {"files": []})
    entry.setdefault("files", []).append(
        {
            "file": str(target.relative_to(ROOT)).replace("\\", "/"),
            "sha256": digest,
            "bytes": len(body),
            "source_url": args.url,
            "note": args.note or "",
            "retrieved_at": time.strftime("%Y-%m-%d %H:%M"),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest 已更新（{key}）")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """翻页检索栏目文章（走站点的 dataproxy.jsp 分页接口），按关键词过滤。

    站点列表页只在首页放最近若干条，历史文章必须靠这个接口翻页。
    单线程 + 每条间隔 2 秒；默认最多翻 ``--pages`` 页。
    """
    base = (
        "https://www.zjzs.net/module/web/jpage/dataproxy.jsp"
        f"?page={{page}}&webid=1&path=/&columnid={args.column}&unitid=100"
        "&webname=%25E6%25B5%2599%25E6%25B1%259F%25E7%259C%2581%25E6%2595%2599%25E8%2582%25B2%25E8%2580%2583%25E8%25AF%2595%25E9%2599%25A2%25E5%25AE%2598%25E7%25BD%2591"
        "&permissiontype=0"
    )
    pattern = re.compile(
        r'href="(/art/\d{4}/\d+/\d+/art_\d+_\d+\.html)"[^>]*title="([^"]*)"', re.S
    )
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, args.pages + 1):
        status, body, headers = fetch(base.format(page=page))
        if status != 200:
            print(f"page={page} → HTTP {status}，停止")
            break
        text = decode(body, headers)
        found = pattern.findall(text)
        if not found:
            print(f"page={page} → 0 条，停止")
            break
        new = [(href, title.strip()) for href, title in found if title not in seen]
        for href, title in new:
            seen.add(title)
            if any(keyword in title for keyword in args.keyword):
                hits.append((href, title))
        print(f"page={page} → {len(found)} 条（新增 {len(new)}），累计匹配 {len(hits)}")
        if len(hits) >= args.limit:
            break

    print()
    for href, title in hits:
        print(f"{title}\n    https://www.zjzs.net{href}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="zjzs.net 抓取工具（robots 优先、单线程、带延迟）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("robots").set_defaults(func=cmd_robots)

    page = sub.add_parser("page")
    page.add_argument("url")
    page.add_argument("--save", default="")
    page.add_argument("--all-links", type=int, default=0)
    page.set_defaults(func=cmd_page)

    listing = sub.add_parser("list", help="翻页检索栏目标题")
    listing.add_argument("--column", default="45", help="栏目 id（45 = 统一高考）")
    listing.add_argument("--pages", type=int, default=12)
    listing.add_argument("--limit", type=int, default=40)
    listing.add_argument("--keyword", action="append", default=[], help="标题关键词，可多次传入")
    listing.set_defaults(func=cmd_list)

    down = sub.add_parser("download")
    down.add_argument("url")
    down.add_argument("--year", type=int, required=True)
    down.add_argument("--out-name", default="")
    down.add_argument("--note", default="")
    down.set_defaults(func=cmd_download)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
