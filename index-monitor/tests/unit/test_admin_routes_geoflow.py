"""admin_routes 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_admin_routes_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/api/admin_routes.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution", (
                        "admin_routes.py 仍 import GeoflowArticleDistribution"
                    )


def test_admin_routes_imports_repository():
    path = pathlib.Path("app/api/admin_routes.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found, "admin_routes.py 未从 app.integration.geoflow 导入"
