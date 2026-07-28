"""trend_routes 已改用 GeoflowRepository（验证不再直接 import GeoflowArticleDistribution）。"""
import ast
import pathlib


def test_trend_routes_no_longer_imports_geoflow_models():
    """trend_routes.py 不应再直接 import GeoflowArticleDistribution。"""
    path = pathlib.Path("app/api/trend_routes.py")
    tree = ast.parse(path.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    imports.append(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if "geoflow_models" in alias.name:
                    imports.append(alias.name)
    assert "GeoflowArticleDistribution" not in imports, (
        "trend_routes.py 仍直接 import GeoflowArticleDistribution，应改用 GeoflowRepository"
    )


def test_trend_routes_imports_repository():
    """trend_routes.py 应 import GeoflowRepository。"""
    path = pathlib.Path("app/api/trend_routes.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow" in node.module and "integration" in node.module:
                found = True
                break
    assert found, "trend_routes.py 未从 app.integration.geoflow 导入"
