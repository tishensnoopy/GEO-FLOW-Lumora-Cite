"""DeepSeek 客户端测试。"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.deepseek_client import ask_deepseek, DeepSeekError


@pytest.mark.asyncio
async def test_ask_deepseek_success():
    """正常调用返回 AI 回答文本。"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "这是 AI 回答"}}]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        result = await ask_deepseek(
            api_key="sk-test",
            prompt="你好",
            system_prompt="你是助手",
        )
        assert result == "这是 AI 回答"


@pytest.mark.asyncio
async def test_ask_deepseek_api_error():
    """API 返回错误时抛 DeepSeekError。"""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Authentication Fails"

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        with pytest.raises(DeepSeekError):
            await ask_deepseek(api_key="sk-invalid", prompt="你好")


@pytest.mark.asyncio
async def test_ask_deepseek_empty_response():
    """空回答返回空字符串而非报错。"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": ""}}]
    }

    with patch("app.services.deepseek_client.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        result = await ask_deepseek(api_key="sk-test", prompt="你好")
        assert result == ""
