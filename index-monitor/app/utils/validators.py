# index-monitor/app/utils/validators.py
"""输入校验工具函数。

设计文档第 9.4 节：密码强度校验（至少 8 位，含字母+数字）。
复用于客户创建/修改密码/admin 重置密码。
"""
import re

from fastapi import HTTPException


def validate_password_strength(password: str) -> None:
    """校验密码强度：至少 8 位，包含字母和数字。

    Parameters
    ----------
    password : str
        待校验的明文密码。

    Raises
    ------
    HTTPException
        - 400：密码少于 8 位
        - 400：密码不含字母
        - 400：密码不含数字
    """
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if not re.search(r'[a-zA-Z]', password):
        raise HTTPException(status_code=400, detail="密码必须包含字母")
    if not re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="密码必须包含数字")
