"""M0 冒烟测试：服务能起、核心模型能导入（AGENTS.md M0 完成定义）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_core_models_importable() -> None:
    """M0 验收命令第 5 步的测试化：核心模型可导入。"""
    from app.core.models import AdmissionUnit, ProbabilityResult, StudentProfile, VolunteerPlan

    assert AdmissionUnit is not None
    assert ProbabilityResult is not None
    assert StudentProfile is not None
    assert VolunteerPlan is not None


def test_model_params_defaults_come_from_domain_rules() -> None:
    """禁魔数纪律：ModelParams 默认值必须与 docs/DOMAIN_RULES.md §3 一致。"""
    from app.core.models import ModelParams

    p = ModelParams()
    assert p.history_years == 3
    assert p.year_weights == [0.5, 0.3, 0.2]
    assert p.plan_beta == 0.4
    assert p.tier_bounds["WEN"] == (0.40, 0.75)
    # 配额：2026-09 / ADR-019 由 25/40/25/10 改为 冲+稳=75%（冲≈稳）、保+垫=25%
    assert p.quota == {"CHONG": 0.375, "WEN": 0.375, "BAO": 0.1875, "DIAN": 0.0625}
    # 语义不变量（比具体数字更重要，防止以后调参把结构改坏）
    assert p.quota["CHONG"] == p.quota["WEN"], "冲与稳应数量相近"
    assert abs((p.quota["CHONG"] + p.quota["WEN"]) - 0.75) < 1e-9, "冲+稳应为 75%"
    assert abs((p.quota["BAO"] + p.quota["DIAN"]) - 0.25) < 1e-9, "保+垫应为 25%"
    # safety_margin 经回测标定：0.15 → 0.30（M2）→ 0.60（M5 修正 M1 数据缺陷后重标定）
    # DOMAIN_RULES §3.1 纪律：任何参数改动必须重跑回测并附前后对比，见 DECISIONS ADR-014
    assert p.safety_margin == 0.60
