# index-monitor/app/services/scan_task_manager.py
"""扫描任务管理器——内存存储扫描任务状态和日志。

用于前端活动窗口实时显示扫描进度，解决"扫描是黑盒"的问题。

设计：
- 任务存储在内存 dict 中（服务重启后清除，扫描任务是临时的，可接受）
- batch-scan 端点创建任务，返回 task_id
- _run_batch_scan 执行过程中通过 add_log / update_progress 写入状态
- 前端轮询 GET /admin/scan/status/{task_id} 获取实时日志
- 自动清理超过 1 小时的旧任务
"""
import threading
from datetime import datetime, timezone
from typing import Optional

# 线程安全的内存任务存储
_tasks: dict[str, dict] = {}
_lock = threading.Lock()


def create_task(scan_type: str, total: int, targets: list[tuple[str, str]]) -> str:
    """创建扫描任务，返回 task_id。

    Parameters
    ----------
    scan_type : str
        'index' / 'citation' / 'both'
    total : int
        待检测的 URL 总数
    targets : list[tuple[str, str]]
        [(url, client_id), ...] 用于日志展示
    """
    import uuid
    task_id = str(uuid.uuid4())
    with _lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "scan_type": scan_type,
            "status": "running",  # running / completed / failed
            "total": total,
            "processed": 0,
            "success": 0,
            "failed": 0,
            "logs": [{
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "info",
                "message": f"扫描任务已启动，共 {total} 条链接待检测（类型: {scan_type}）",
            }],
            "targets": [{"url": url, "client_id": cid} for url, cid in targets],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    return task_id


def add_log(task_id: str, level: str, message: str) -> None:
    """添加日志条目。

    Parameters
    ----------
    level : str
        'info' / 'success' / 'warning' / 'error'
    """
    with _lock:
        if task_id not in _tasks:
            return
        _tasks[task_id]["logs"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
        })
        _tasks[task_id]["updated_at"] = datetime.now(timezone.utc).isoformat()


def update_progress(
    task_id: str,
    processed: Optional[int] = None,
    success: Optional[int] = None,
    failed: Optional[int] = None,
) -> None:
    """更新进度计数。"""
    with _lock:
        if task_id not in _tasks:
            return
        if processed is not None:
            _tasks[task_id]["processed"] = processed
        if success is not None:
            _tasks[task_id]["success"] = success
        if failed is not None:
            _tasks[task_id]["failed"] = failed
        _tasks[task_id]["updated_at"] = datetime.now(timezone.utc).isoformat()


def complete_task(task_id: str, status: str = "completed") -> None:
    """标记任务完成。"""
    with _lock:
        if task_id not in _tasks:
            return
        _tasks[task_id]["status"] = status
        _tasks[task_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _tasks[task_id]["logs"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "success" if status == "completed" else "error",
            "message": (
                f"扫描任务结束：{_tasks[task_id]['success']} 成功 / "
                f"{_tasks[task_id]['failed']} 失败 / "
                f"{_tasks[task_id]['total']} 总计"
            ),
        })


def get_task(task_id: str) -> Optional[dict]:
    """获取任务状态（含日志）。"""
    with _lock:
        task = _tasks.get(task_id)
        if task is None:
            return None
        # 返回副本，避免外部修改
        return {
            "task_id": task["task_id"],
            "scan_type": task["scan_type"],
            "status": task["status"],
            "total": task["total"],
            "processed": task["processed"],
            "success": task["success"],
            "failed": task["failed"],
            "logs": list(task["logs"]),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }


def cleanup_old_tasks(max_age_seconds: int = 3600) -> None:
    """清理超过 max_age_seconds 的旧任务。"""
    now = datetime.now(timezone.utc)
    to_remove = []
    with _lock:
        for task_id, task in _tasks.items():
            try:
                updated = datetime.fromisoformat(task["updated_at"])
                if (now - updated).total_seconds() > max_age_seconds:
                    to_remove.append(task_id)
            except (ValueError, KeyError):
                to_remove.append(task_id)
        for task_id in to_remove:
            del _tasks[task_id]
