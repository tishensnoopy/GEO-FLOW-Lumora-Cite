"""distribution_query 已改用 GeoflowRepository。"""
import ast
import pathlib


def test_distribution_query_no_longer_imports_geoflow_models():
    path = pathlib.Path("app/services/distribution_query.py")
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "geoflow_models" in node.module:
                names = [alias.name for alias in node.names]
                assert "GeoflowArticleDistribution" not in names
                assert "GeoflowArticle" not in names
                assert "GeoflowDistributionChannel" not in names


def test_distribution_query_imports_repository():
    path = pathlib.Path("app/services/distribution_query.py")
    tree = ast.parse(path.read_text())
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "integration.geoflow" in (node.module or ""):
                found = True
                break
    assert found
