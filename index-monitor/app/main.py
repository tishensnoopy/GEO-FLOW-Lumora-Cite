# index-monitor/app/main.py（完整版本）
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router
from app.api.sso_routes import router as sso_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.utils.http_client import http_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    # 关闭顺序：先停调度器（不再派发新任务），再关闭 HTTP 客户端（释放连接池）
    stop_scheduler()
    await http_client.close()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

# SSO 路由不挂 /api/v1 前缀：
# 1. callback 是 GEOFlow 回跳的目标 URL，顶层路径 /sso/callback 更直观；
# 2. 前端可直接 window.location.href='/sso/login' 触发跳转，无需拼接 /api/v1；
# 3. 与 GEOFlow SsoController 约定的 redirect_uri=https://monitor.zkeeeai.com/sso/callback 一致。
app.include_router(sso_router)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
