# index-monitor/tests/unit/test_change_password.py
"""客户改密码测试。设计文档第 9.3 节。"""
import pytest

from app.core.security import hash_password, verify_password
from app.utils.validators import validate_password_strength
from fastapi import HTTPException


def test_validate_password_rejects_short():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("ab1")
    assert exc.value.status_code == 400


def test_validate_password_rejects_no_letter():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("12345678")
    assert "字母" in exc.value.detail


def test_validate_password_rejects_no_digit():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("abcdefgh")
    assert "数字" in exc.value.detail


def test_validate_password_accepts_strong():
    validate_password_strength("Strong123")


def test_hash_and_verify_password():
    """hash_password + verify_password 往返。"""
    hashed = hash_password("MyPass123")
    assert verify_password("MyPass123", hashed) is True
    assert verify_password("wrong", hashed) is False
