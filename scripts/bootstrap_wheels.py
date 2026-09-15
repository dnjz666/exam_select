"""离线引导脚本：从 PyPI 镜像直连抓取本机安装所需 wheel，绕开代理/索引环境问题。

背景（2026-02，本机实测，见 docs/DECISIONS.md）：
- 本沙箱内 curl.exe(Schannel) 与 PowerShell IWR/HttpClient 的 HTTPS 均不可用；
- python urllib 直连清华镜像正常（<1s），但 pip 的 requests 子进程会冻结；
- 因此用 stdlib urllib 下载 wheel，再 `pip install --no-index --find-links` 离线安装。

用法：
    py -3.11 scripts/bootstrap_wheels.py            # 抓取到 data/wheels/
    py -3.11 -m pip install --no-index --find-links data/wheels -e "backend[dev]"
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
from pathlib import Path

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple/{pkg}/"
OUT = Path(__file__).resolve().parent.parent / "data" / "wheels"

# backend/pyproject.toml dependencies + dev extras 的传递依赖（Python 3.11 / Windows）
PACKAGES = [
    # runtime
    "fastapi", "starlette", "anyio", "sniffio", "idna", "typing-extensions",
    "pydantic", "pydantic-core", "annotated-types", "typing-inspection", "annotated-doc",
    "pydantic-settings", "python-dotenv",
    "uvicorn", "click", "h11", "httptools", "pyyaml", "watchfiles", "websockets",
    "sqlalchemy", "greenlet",
    # build backend（editable 构建隔离环境需要）
    "setuptools", "wheel",
    # dev / tests
    "pytest", "iniconfig", "packaging", "pluggy", "colorama", "pygments",
    "pytest-cov", "coverage",
    "hypothesis", "attrs", "sortedcontainers",
    "httpx", "httpcore", "certifi",
]

WHEEL_RE = re.compile(
    r"-(?P<py>cp311|py3|py2\.py3|py39|py310|py312|cp312)-"
    r"(?P<abi>cp311|cp312|abi3|none)-"
    r"(?P<plat>win_amd64|any)\.whl$",
    re.IGNORECASE,
)
PRERELEASE_RE = re.compile(r"[abc]\d+$|\.dev\d+$|rc\d+$", re.IGNORECASE)

# 上游钉死精确版本的包（如 pydantic-core==x 由 pydantic 精确 pin）；留空则取最新稳定版
EXACT_VERSIONS: dict[str, str] = {"pydantic-core": "2.46.5"}


def anchor_name(text: str) -> str:
    """镜像 HTML 中 <a> 的 text 可能带尾部空格/锚点，规整为纯文件名。"""
    return text.strip()


def version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for seg in version.split("."):
        m = re.match(r"\d+", seg)
        parts.append(int(m.group()) if m else 0)
    return tuple(parts)


def pick_wheel(pkg: str, html: str) -> tuple[str, str] | None:
    """返回 (下载 URL, 文件名)。选最新版本，同版本优先 cp311/win_amd64。"""
    best: tuple[tuple[int, ...], int, str, str] | None = None
    for m in re.finditer(r'<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<text>[^<]+\.whl)</a>', html):
        fname = anchor_name(m.group("text"))
        wm = WHEEL_RE.search(fname)
        if not wm or PRERELEASE_RE.search(fname):
            continue
        name_ver = fname[: wm.start()]
        bits = name_ver.split("-")
        if len(bits) < 2:
            continue
        version = bits[1]
        if version.lower().startswith("v"):
            version = version[1:]
        # 预发布检查必须针对版本段（整个文件名以 .whl 结尾，$ 锚定会失效）
        if PRERELEASE_RE.search(version):
            continue
        pinned = EXACT_VERSIONS.get(pkg.lower().replace("_", "-"))
        if pinned is not None and version != pinned:
            continue
        score = version_key(version)
        # 同版本时优先平台二进制 wheel
        plat_bonus = 1 if wm.group("plat").lower() == "win_amd64" else 0
        cand = (score, plat_bonus, fname, m.group("url"))
        if best is None or (cand[0], cand[1]) > (best[0], best[1]):
            best = cand
    if best is None:
        return None
    url = best[3]
    if url.startswith("../"):
        url = "https://pypi.tuna.tsinghua.edu.cn/simple/" + pkg + "/" + url
    return url, best[2]


def fetch(pkg: str, dest_dir: Path, retries: int = 3) -> Path | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 直连，不走代理
    url = MIRROR.format(pkg=pkg)
    for attempt in range(1, retries + 1):
        try:
            with opener.open(url) as r:
                html = r.read().decode("utf-8", "replace")
            picked = pick_wheel(pkg, html)
            if picked is None:
                print(f"[SKIP] {pkg}: 未找到匹配 cp311/py3 wheel")
                return None
            dl_url, fname = picked
            dest = dest_dir / fname
            if dest.exists() and dest.stat().st_size > 10_000:
                print(f"[HAVE] {fname}")
                return dest
            t0 = time.time()
            with opener.open(dl_url) as r, open(dest, "wb") as f:
                while chunk := r.read(1 << 16):
                    f.write(chunk)
            size_kb = dest.stat().st_size // 1024
            print(f"[OK]   {fname} ({size_kb} KB, {time.time() - t0:.1f}s)")
            return dest
        except Exception as e:  # noqa: BLE001
            print(f"[RETRY {attempt}/{retries}] {pkg}: {type(e).__name__}: {e}")
            time.sleep(2 * attempt)
    print(f"[FAIL] {pkg}")
    return None


def main() -> int:
    dest_dir = OUT
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"下载目标: {dest_dir}")
    failed: list[str] = []
    for pkg in PACKAGES:
        if fetch(pkg, dest_dir) is None:
            failed.append(pkg)
    print()
    wheels = sorted(dest_dir.glob("*.whl"))
    print(f"完成：{len(wheels)} 个 wheel 就绪于 {dest_dir}")
    if failed:
        print("失败包：", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
