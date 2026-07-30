# index-monitor/app/core/security.py
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import bcrypt
from app.core.config import settings

# 兼容性修复：passlib 1.7.4 与 bcrypt 5.0 不兼容（passlib 内部传给 bcrypt 的
# 数据超过 72 字节限制，bcrypt 5.0 不再自动截断而是抛 ValueError）。
# 直接使用 bcrypt 库，跳过 passlib，同时保持 hash 格式兼容（$2b$ 前缀）。
_BCRYPT_MAX_BYTES = 72


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    # datetime.utcnow() 在 Python 3.12+ 已废弃，改用 timezone-aware UTC
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return {}

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与 hash 是否匹配。

    手动截断至 72 字节（bcrypt 5.0 不再自动截断），与旧 passlib 行为一致，
    确保已存储的 hash 仍可验证。
    """
    pwd_bytes = plain_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False

def hash_password(password: str) -> str:
    """生成 bcrypt hash。

    手动截断至 72 字节（bcrypt 5.0 不再自动截断），返回 $2b$ 前缀的标准 hash。
    """
    pwd_bytes = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")
