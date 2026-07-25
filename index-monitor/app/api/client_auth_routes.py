# index-monitor/app/api/client_auth_routes.py
"""客户认证端点：登录 + 改密码 + 修改资料。

设计文档第 5.4 节（登录）+ 第 9.3 节（改密码/资料）。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.client import Client
from app.utils.validators import validate_password_strength

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    client_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


@router.post("/auth/login")
async def client_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """客户独立登录。"""
    result = await db.execute(
        select(Client).where(Client.client_id == req.client_id, Client.status == "active")
    )
    client = result.scalar_one_or_none()
    if not client or not verify_password(req.password, client.password_hash):
        raise HTTPException(status_code=401, detail="客户账号或密码错误")

    from sqlalchemy.sql import func
    client.last_login_at = func.now()
    await db.commit()

    token = create_access_token({"sub": client.client_id, "role": "client", "type": "client"})
    return {"access_token": token, "token_type": "bearer", "role": "client"}


@router.put("/auth/password")
async def change_password(
    req: ChangePasswordRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户修改自己的密码。需验证旧密码 + 新密码强度 + 新旧不同。"""
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可修改密码")

    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误")

    if req.old_password == req.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与旧密码相同")

    validate_password_strength(req.new_password)

    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"message": "密码修改成功"}


@router.put("/auth/profile")
async def update_profile(
    req: UpdateProfileRequest,
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """客户修改自己的资料（联系人/电话）。client_id 和 email 不可改。"""
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="仅客户可修改资料")

    if req.contact_name is not None:
        user.contact_name = req.contact_name
    if req.contact_phone is not None:
        user.contact_phone = req.contact_phone
    await db.commit()
    return {"message": "资料更新成功"}
