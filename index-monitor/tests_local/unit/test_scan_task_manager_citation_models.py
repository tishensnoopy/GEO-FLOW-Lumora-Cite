# index-monitor/tests/unit/test_scan_task_manager_citation_models.py
"""scan_task_manager 采信模型状态结构化测试（阶段 4 - ⑤ 后端支撑）。

验证目标：
1. create_task 初始化空 citation_models
2. update_citation_model 增加模型条目
3. 同一模型重复上报覆盖（重试场景）
4. get_task 返回 citation_models 为 list
5. 无 task_id 时 update_citation_model 是 no-op

这让 ScanPanel 的"采信模型状态卡片"能直接读 task.citation_models，
而非从日志文本脆弱解析。
"""
import pytest

from app.services import scan_task_manager as stm


def test_create_task_has_empty_citation_models():
    task_id = stm.create_task("citation", 1, [("https://x.com", "c1")])
    task = stm.get_task(task_id)
    assert task["citation_models"] == []


def test_update_citation_model_adds_entry():
    task_id = stm.create_task("citation", 1, [("https://x.com", "c1")])
    stm.update_citation_model(task_id, "千问", "verified")
    task = stm.get_task(task_id)
    models = task["citation_models"]
    assert len(models) == 1
    assert models[0] == {"model": "千问", "status": "verified", "error": None}


def test_update_citation_model_multiple_models():
    task_id = stm.create_task("citation", 1, [("https://x.com", "c1")])
    stm.update_citation_model(task_id, "千问", "verified")
    stm.update_citation_model(task_id, "豆包", "error", error="401 Unauthorized")
    task = stm.get_task(task_id)
    by_name = {m["model"]: m for m in task["citation_models"]}
    assert by_name["千问"]["status"] == "verified"
    assert by_name["豆包"]["status"] == "error"
    assert by_name["豆包"]["error"] == "401 Unauthorized"


def test_update_citation_model_overwrites_same_model():
    """同一模型重复上报（如重试）应覆盖旧状态。"""
    task_id = stm.create_task("citation", 1, [("https://x.com", "c1")])
    stm.update_citation_model(task_id, "千问", "error", error="超时")
    stm.update_citation_model(task_id, "千问", "verified")
    task = stm.get_task(task_id)
    models = task["citation_models"]
    assert len(models) == 1, "同一模型重复上报不应产生重复条目"
    assert models[0]["status"] == "verified"
    assert models[0]["error"] is None


def test_update_citation_model_unknown_task_is_noop():
    """不存在的 task_id 不应抛错。"""
    stm.update_citation_model("nonexistent", "千问", "verified")  # 不应抛异常


def test_index_task_also_has_citation_models_field():
    """收录任务也应返回 citation_models（空 list），保证前端字段稳定。"""
    task_id = stm.create_task("index", 1, [("https://x.com", "c1")])
    task = stm.get_task(task_id)
    assert task["citation_models"] == []
