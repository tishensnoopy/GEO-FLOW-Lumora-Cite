# index-monitor/tests/unit/test_no_geoflow_models.py
"""geoflow_models.py 已删除，生产代码不再引用它。

任务 11 收尾：GEOFlow schema 依赖完全隔离到防腐层
（``app/integration/geoflow/``），生产代码（``app/``）不再 import
``app.models.geoflow_models``。

测试代码允许保留自己的 GEOFlow ORM 测试替身
（``tests/_geoflow_test_models.py``）用于播种测试数据——这是测试关注点，
不破坏防腐层隔离（生产代码零引用）。
"""
import pathlib
import subprocess


def test_geoflow_models_file_deleted():
    """``app/models/geoflow_models.py`` 必须已删除。"""
    path = pathlib.Path("app/models/geoflow_models.py")
    assert not path.exists(), f"{path} 仍存在，防腐层隔离未完成"


def test_no_app_code_references_geoflow_models():
    """生产代码（``app/``）不应再出现 ``geoflow_models`` 字样。

    用 grep 检查任何形式的引用（import / from / 注释 / 字符串），
    确保防腐层与旧 ORM 模型完全解耦。``reader.py`` 内部有自己的独立
    ORM 定义，不依赖 ``geoflow_models``。
    """
    result = subprocess.run(
        ["grep", "-rn", "geoflow_models", "app/", "--include=*.py"],
        capture_output=True,
        text=True,
    )
    assert result.stdout == "", (
        f"app/ 中仍有 geoflow_models 引用：\n{result.stdout}"
    )
