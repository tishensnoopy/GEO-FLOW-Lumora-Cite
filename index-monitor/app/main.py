# index-monitor/app/main.py（完整版本）
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.redis import close_redis
from app.api.routes import router
from app.api.sso_routes import router as sso_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.utils.http_client import http_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    # 关闭顺序：先停调度器（不再派发新任务），再关闭 HTTP 客户端（释放连接池），
    # 最后关闭 Redis 连接（SSO state 存储用，参考 http_client.close() 模式）
    stop_scheduler()
    await http_client.close()
    await close_redis()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

# 客户认证路由：POST /auth/login（client_id 登录）+ PUT /auth/password（改密码）
# + PUT /auth/profile（修改资料）。设计文档第 5.4 节 + 第 9.3 节。
# 控制者裁定：统一用 client_id 登录（更稳定的业务标识符），原 routes.py 中的
# username 登录端点已删除避免路由冲突。
from app.api.client_auth_routes import router as client_auth_router
app.include_router(client_auth_router, prefix="/api/v1")

# SSO 路由不挂 /api/v1 前缀：
# 1. callback 是 GEOFlow 回跳的目标 URL，顶层路径 /sso/callback 更直观；
# 2. 前端可直接 window.location.href='/sso/login' 触发跳转，无需拼接 /api/v1；
# 3. 与 GEOFlow SsoController 约定的 redirect_uri=https://monitor.zkeeeai.com/sso/callback 一致。
app.include_router(sso_router)

# admin 后台路由：客户生命周期 + 站点管理 + 手动录入 + 批量检测（设计文档第 9 节）
from app.api.admin_routes import router as admin_router
app.include_router(admin_router, prefix="/api/v1")

# 手动录入端点专用 router（无 /admin 前缀，POST /api/v1/distributions）：
# 控制者裁定——测试期望 POST /api/v1/distributions（无 /admin），
# GET /api/v1/admin/distributions（有 /admin），两个端点分别挂在不同 router 上。
from app.api.admin_routes import distribution_router
app.include_router(distribution_router, prefix="/api/v1")

# 导出端点（设计文档第 12.3 节）：
# - POST /api/v1/admin/exports（admin 导出全部 / 指定客户）
# - POST /api/v1/exports（客户导出自己）
# - GET /api/v1/exports（分页列表，admin 全部 / client 自己）
# - GET /api/v1/exports/{task_id}（查状态，client 403 隔离）
# - GET /api/v1/exports/{task_id}/download（下载，client 403 隔离）
# 端点只创建 ExportTask 记录（status="pending"）立即返回 202，
# 实际导出处理由 ExportService（M3 任务 4）异步执行，不在请求路径内同步调用。
from app.api.export_routes import router as export_router
app.include_router(export_router, prefix="/api/v1")

# Dashboard 趋势数据 API（设计文档 Dashboard StatCard sparkline + 同比数据源）：
# 路由内部 prefix="/admin/dashboard"，配合此处的 "/api/v1" 前缀，
# 最终路径为 /api/v1/admin/dashboard/trend。
from app.api.trend_routes import router as trend_router
app.include_router(trend_router, prefix="/api/v1")

# 客户问题管理路由（设计文档 Phase 3）：
# - 运营端 CRUD: /admin/clients/{client_id}/questions
# - 客户端只读: /questions
from app.api.client_question_routes import router as client_question_router
app.include_router(client_question_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
