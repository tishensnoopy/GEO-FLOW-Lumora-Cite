# index-monitor/tests/unit/test_validators.py
"""密码强度校验测试。设计文档第 9.4 节。"""
import pytest
from fastapi import HTTPException

from app.utils.validators import validate_password_strength


def test_password_too_short_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("ab1")
    assert exc.value.status_code == 400
    assert "至少 8 位" in exc.value.detail


def test_password_no_letter_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("12345678")
    assert "字母" in exc.value.detail


def test_password_no_digit_raises():
    with pytest.raises(HTTPException) as exc:
        validate_password_strength("abcdefgh")
    assert "数字" in exc.value.detail


def test_password_valid_passes():
    # 不抛异常即通过
    validate_password_strength("abc12345")
    validate_password_strength("PassWord2026")


def test_password_exactly_8_chars_passes():
    validate_password_strength("a1b2c3d4")
