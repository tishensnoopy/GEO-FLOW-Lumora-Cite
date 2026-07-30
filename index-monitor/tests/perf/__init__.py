# index-monitor/tests/perf/__init__.py
"""AI 采信扫描流水线性能测试包。

本包下的测试用 mock 隔离外部依赖（DeepSeek API、爬虫、联网检测），
只测本地代码路径的性能。真实 PG 连接仅用于 advisory lock 测试
（test_perf_scan_lock.py）。

运行：在 index-monitor 根目录执行
    source venv/bin/activate
    pytest -p no:cacheprovider tests/perf/ -s
"""
