# index-monitor/app/main.py（完整版本）
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router
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

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
