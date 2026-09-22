"""计算结果持久缓存（ADR-019）—— 让"相似问题"下次直接复用。

## 为什么需要（与 ADR-016 的分工）

ADR-016 的缓存是**进程内**的（``repositories._cache`` / ``probability._RESULT_CACHE``）：
同一会话里"推荐页 → 生成志愿表 → 手改重算 → 风险扫描"不重复算，**但进程重启就没了**。
实测浙江真实数据下一次推荐：热缓存 0.5–1.0s、冷启动约 4s（要读 5.8 万行、算 1.5 万个单位）。
考生/老师第二天打开同一个分数段的问题，又要冷启动一次 —— 本模块解决这一段。

## 缓存什么、为什么安全

缓存 ``recommend`` 的**完整响应体**。它是**考生无关**的：

* ``item_payload`` 里没有 ``student_id``（只有 unit / college / major / 概率 / 效用 / 证据链）；
* 概率只依赖考生的**位次**，不依赖分数、姓名（``probability.estimate_probability`` 文档已声明）；
* 效用只依赖 ``(unit, college, major, preferences)``，而 preferences 已并入键的指纹。

因此"同位次 + 同筛选"的**另一位考生**可以安全复用，不会串号。

## 失效策略（宁可多失效一次，也不要读到旧数据）

键里含 ``data_version`` —— 一个**持久化**的数据代次令牌（``app_meta`` 表）：

* 重新播种（``seed.py``）与任何回填/重归类脚本都会 ``bump_data_version()``；
* 读取时 ``data_version`` 不等即视为未命中（旧行留着不删，便于观察，也可用
  :func:`clear` 清理）；
* 参数 / 筛选 / limit 变化会生成不同的 ``cache_key``，天然不命中；
* **绝不用"行数是否变化"判断**：实测回填 ``majors.category`` 时行数没变、归类全变了。

★ 这条纪律与 ADR-016 的"缓存键必须含目标计划数、不要用 ``id()`` 做键"同源：
**键漏掉任何一个影响结果的输入，就是一次静默的错误建议。**
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models as db
from app.db.repositories import now_iso

#: 数据代次令牌的 app_meta 键名
DATA_VERSION_KEY = "data_version"

#: 初始代次（全新库、尚未 bump 过时使用）
INITIAL_DATA_VERSION = "0"


def get_data_version(session: Session) -> str:
    """读当前数据代次；库里没有则返回初始值（**不写库**，读路径必须无副作用）。"""
    row = session.get(db.AppMeta, DATA_VERSION_KEY)
    return row.value if row is not None else INITIAL_DATA_VERSION


def bump_data_version(session: Session, *, note: str = "") -> str:
    """数据被改动后调用：把代次推进一位，使**所有**持久缓存失效。

    由 ``seed.py`` 与回填/重归类脚本在提交后调用。返回值是新代次。
    """
    current = get_data_version(session)
    try:
        nxt = str(int(current) + 1)
    except ValueError:  # 兼容被手工改过的值
        nxt = hashlib.sha1(f"{current}|{now_iso()}".encode()).hexdigest()[:12]
    stamp = now_iso()
    row = session.get(db.AppMeta, DATA_VERSION_KEY)
    if row is None:
        session.add(db.AppMeta(key=DATA_VERSION_KEY, value=nxt, updated_at=stamp))
    else:
        row.value = nxt
        row.updated_at = stamp
    session.flush()
    return nxt


# ---------------------------------------------------------------------------
# 指纹
# ---------------------------------------------------------------------------
def _digest(payload: Any) -> str:
    """稳定指纹：键排序 + 紧凑分隔符，避免 dict 顺序造成假不命中。"""
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint_recommend(
    *,
    data_version: str,
    province: str,
    year: int,
    rank: int,
    criteria: Any,
    weights: Any,
    params: Any,
    limit: int,
    include_too_risky: bool,
    allowed_batches: Any,
    intent_as_hard: bool,
) -> tuple[str, str]:
    """算 ``recommend`` 的缓存键与人类可读摘要。

    ★ 键必须覆盖**每一个影响结果的输入**。漏一个 = 静默的错误建议（ADR-016 同源教训）。
    """
    parts = {
        "v": data_version,
        "province": province,
        "year": year,
        "rank": rank,
        "criteria": (
            criteria.model_dump(mode="json") if hasattr(criteria, "model_dump") else criteria
        ),
        "weights": weights,
        "params": params.model_dump(mode="json") if hasattr(params, "model_dump") else params,
        "limit": limit,
        "include_too_risky": include_too_risky,
        "allowed_batches": sorted(allowed_batches) if allowed_batches else None,
        "intent_as_hard": intent_as_hard,
    }
    label = (
        f"recommend/{province}/{year}/rank={rank}/limit={limit}"
        f"/risky={int(include_too_risky)}/hard={int(intent_as_hard)}/v={data_version}"
    )
    return _digest(parts), label


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------
def cache_get(session: Session, cache_key: str, data_version: str) -> dict | None:
    """命中则返回 payload（并累加命中计数）；未命中/代次不符 → ``None``。

    ★ 代次不符时**不删旧行**：留着便于运维观察"哪些旧结论还在"，由 :func:`clear` 统一清理。
    """
    row = session.get(db.ResultCache, cache_key)
    if row is None or row.data_version != data_version:
        return None
    row.hits += 1
    row.last_hit_at = now_iso()
    session.flush()
    try:
        return json.loads(row.payload)
    except json.JSONDecodeError:  # 损坏的缓存行按未命中处理，不让它拖垮请求
        return None


def cache_put(
    session: Session,
    cache_key: str,
    *,
    data_version: str,
    kind: str,
    label: str,
    payload: dict,
) -> None:
    """写入缓存（同键覆盖）。"""
    text = json.dumps(payload, ensure_ascii=False)
    row = session.get(db.ResultCache, cache_key)
    if row is None:
        session.add(
            db.ResultCache(
                cache_key=cache_key,
                data_version=data_version,
                kind=kind,
                label=label,
                payload=text,
                created_at=now_iso(),
                hits=0,
                last_hit_at=None,
            )
        )
    else:
        row.data_version = data_version
        row.kind = kind
        row.label = label
        row.payload = text
        row.created_at = now_iso()
    session.flush()


def stats(session: Session) -> dict:
    """缓存概况（供运维与 UI 展示"复用了多少"）。"""
    rows = list(session.execute(select(db.ResultCache)).scalars())
    current = get_data_version(session)
    fresh = [r for r in rows if r.data_version == current]
    return {
        "data_version": current,
        "entries": len(rows),
        "entries_current_version": len(fresh),
        "stale_entries": len(rows) - len(fresh),
        "total_hits": sum(r.hits for r in rows),
        "kinds": sorted({r.kind for r in rows}),
    }


def clear(session: Session, *, only_stale: bool = False) -> int:
    """清缓存。``only_stale=True`` 时只清代次不符的旧行。返回删除条数。"""
    current = get_data_version(session)
    rows = list(session.execute(select(db.ResultCache)).scalars())
    removed = 0
    for row in rows:
        if only_stale and row.data_version == current:
            continue
        session.delete(row)
        removed += 1
    session.flush()
    return removed


__all__ = [
    "DATA_VERSION_KEY",
    "INITIAL_DATA_VERSION",
    "bump_data_version",
    "cache_get",
    "cache_put",
    "clear",
    "fingerprint_recommend",
    "get_data_version",
    "stats",
]
