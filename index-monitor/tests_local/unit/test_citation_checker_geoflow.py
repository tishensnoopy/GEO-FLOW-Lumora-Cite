"""citation_checker 已改用 GeoflowRepository（仅替换 GEOFlow 查询部分）。"""
import ast
import pathlib


def test_citation_checker_no_longer_imports_geoflow_distribution():
    path = pathlib.Path("app/services/citation_checker.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                for alias in node.names:
                    assert alias.name != "GeoflowArticleDistribution"


def test_citation_checker_imports_repository():
    path = pathlib.Path("app/services/citation_checker.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
