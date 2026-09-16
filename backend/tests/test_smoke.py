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
    assert p.quota == {"CHONG": 0.25, "WEN": 0.40, "BAO": 0.25, "DIAN": 0.10}
    # safety_margin 经回测标定：0.15 → 0.30（M2）→ 0.60（M5 修正 M1 数据缺陷后重标定）
    # DOMAIN_RULES §3.1 纪律：任何参数改动必须重跑回测并附前后对比，见 DECISIONS ADR-014
    assert p.safety_margin == 0.60
