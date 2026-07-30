from fastapi.testclient import TestClient
from app.main import app


def test_health_endpoint_returns_200_and_expected_json():
    """验收标准 1：健康检查接口返回 200 + 正确 JSON。"""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "1.0.0"}
