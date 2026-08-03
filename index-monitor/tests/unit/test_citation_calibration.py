# index-monitor/tests/unit/test_citation_calibration.py
"""CitationCalibration 模型测试。"""
from app.models.citation_calibration import CitationCalibration


def test_model_fields():
    """模型字段完整性检查。"""
    cols = {c.name for c in CitationCalibration.__table__.columns}
    assert cols == {
        "id", "citation_result_id", "platform_id",
        "web_answer", "web_sources", "web_hit_type",
        "api_hit_type", "matches", "note",
        "calibrated_at", "created_at",
    }


def test_model_schema():
    """表属于 monitor schema。"""
    assert CitationCalibration.__table__.schema == "monitor"


def test_unique_constraint():
    """(citation_result_id, platform_id) 唯一约束存在。"""
    constraints = CitationCalibration.__table__.constraints
    uq_names = [c.name for c in constraints if hasattr(c, "name") and c.name]
    assert any("uq_calibration_result_platform" in name for name in uq_names)
