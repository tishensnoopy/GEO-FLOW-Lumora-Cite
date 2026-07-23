import os
import sys

# 让 `app` 包从 index-monitor 项目根可导入，无论 pytest 从哪个目录启动
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
