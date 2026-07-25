# index-monitor/app/utils/validators.py
"""输入校验工具函数。

设计文档第 9.4 节：密码强度校验（至少 8 位，含字母+数字）。
复用于客户创建/修改密码/admin 重置密码。
"""
import re
from urllib.parse import urlsplit

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


def normalize_domain(url_or_host: str | None) -> str:
    """提取并标准化 domain：小写 + 去掉 www. 前缀。

    接受完整 URL 或裸 hostname，返回标准化后的 domain。

    Parameters
    ----------
    url_or_host : str | None
        完整 URL（https://www.example.com/path）或裸 hostname（www.example.com）。

    Returns
    -------
    str
        标准化后的 domain（小写、去 www）。空输入返回空字符串。

    Examples
    --------
    >>> normalize_domain("https://www.example.com/path")
    'example.com'
    >>> normalize_domain("WWW.Example.COM")
    'example.com'
    >>> normalize_domain("blog.example.com")
    'blog.example.com'
    """
    if not url_or_host:
        return ""
    # urlsplit 对裸 hostname 也能处理（path 部分即 hostname）
    host = urlsplit(url_or_host).hostname or urlsplit(url_or_host).path
    host = (host or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host
