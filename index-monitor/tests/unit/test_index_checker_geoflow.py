"""index_checker 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_index_checker_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/services/index_checker.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution"


def test_index_checker_imports_repository():
    path = pathlib.Path("app/services/index_checker.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
