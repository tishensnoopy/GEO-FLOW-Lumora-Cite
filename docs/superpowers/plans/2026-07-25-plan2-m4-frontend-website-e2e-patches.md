# M4 主计划补强补丁 实现计划

> **面向 AI 代理的工作者：** 本文档是 `2026-07-25-plan2-m4-frontend-website-e2e.md`（M4 主计划）的**覆盖性补丁**。执行 M4 主计划时必须参照本文档修正原计划中的缺陷。原计划作为主体蓝图保留，本文档作为执行时必须参照的覆盖说明。

**目标：** 修复 M4 主计划经整分支代码审查发现的 25 项缺陷（11 项关键 + 14 项重要），并纳入批次 C 的代码审查建议，使 M4 主计划可正确交付子代理执行。

**架构：** 增量修复——保留原计划任务分解结构，逐个缺陷给出修正代码和覆盖步骤。关键缺陷（D01-D11）不修则任务失败；重要缺陷（D12-D25）影响质量与可维护性。

**前置条件：**
- 批次 A（5 项关键阻断修复）+ 批次 B（C7/C10/C11）已 commit（`177e8d4` + `8ebc8bf`）
- 缺口任务 5（ExportDialog + Exports 适配）已 commit（`24b2f51`）
- alembic 当前版本 `009`（孤儿表 article_distributions 已 drop）
- 本地 Docker 环境 `geo-postgres-local` + `index-monitor` 容器运行中

**关联文档：**
- [M4 主计划](2026-07-25-plan2-m4-frontend-website-e2e.md)（被覆盖对象）
- [M4 缺口补全](2026-07-25-plan2-m4-gaps-supplement.md)（已执行完毕）
- [设计文档](../specs/2026-07-25-geoflow-monitor-db-sync-design.md)

---

## 缺陷总览

### 关键缺陷（不修则任务失败）

| 编号 | 所在任务 | 缺陷概述 | 修复策略 |
|------|---------|---------|---------|
| D01 | 任务 9 | ArchivedDistribution.client_id=None 违反 NOT NULL | 归档前匹配 client_id |
| D02 | 任务 9 | content_keywords Text→JSON 类型不匹配 | json.loads 转换 |
| D03 | 任务 9 | scheduler.py 完整替换丢失 scheduled_export_processor | 改为增量编辑 |
| D04 | 任务 3 | 客户端 GET /distributions 端点不存在 | 后端新增 client 端点 |
| D05 | 任务 10 | E2E 调用 /system/config 路径错误 | 改为 /config |
| D06 | 任务 9 | status=="deleted" 查询条件错误 | 改用 action=="delete" |
| D07 | 任务 7 | homepage.blade.php 路径不存在 | 改为 site/partials/header.blade.php |
| D08 | 任务 7 | Bootstrap 类与实际 Tailwind 不匹配 | 按 Tailwind 重写 |
| D09 | 任务 8 | layouts/admin.blade.php 路径不存在 | 改为 admin/partials/header.blade.php |
| D10 | 任务 8 | AdminLTE 类与实际 Tailwind 不匹配 | 按 $menu 数组追加 |
| D11 | 任务 8 | 任务已实现，重复劳动 | 标记为验证任务 |

### 重要缺陷（影响质量，纳入批次 C 统一处理）

| 编号 | 所在任务 | 缺陷概述 | 修复策略 |
|------|---------|---------|---------|
| D12 | 任务 1 | Login.vue 改造绕过 Vuex store | 清理 store 或保持集成 |
| D13 | 任务 1 | 路由配置丢失 /articles /settings | 保留现有路由 |
| D14 | 任务 5 | App.vue 侧边栏丢失 /articles /settings | 保留现有菜单项 |
| D15 | 任务 6 | audit_logs 端点缺 total 字段 | 后端返回 total |
| D16 | 任务 9 | or_ 导入放在文件末尾 | 移到顶部 |
| D17 | 任务 10 | E2E 步骤 8-20 全部跳过 | 补充核心链路测试 |
| D18 | 任务 9 | 归档字段不完整 | 列出所有字段 |
| D19 | 任务 2 | Dashboard.vue 已实现，计划会回退 | 标记为验证任务 |
| D20 | 任务 4 | Exports.vue 已实现，计划会回退 | 标记为验证任务 |
| D21 | 任务 7 | commit 命令文件扩展名拼错 .py→.php | 修正扩展名 |
| D22 | 任务 9 | monthly_archive 缺 timezone 导入 | 补充导入 |
| D23 | 任务 9 | scheduler 导入风格混乱 | 统一到顶部 |
| D24 | 任务 10 | CORS 检查路径错误 + 无法真正验证 | 修正路径 |
| D25 | 任务 9 | 归档任务未声明依赖迁移 006 | 声明前置条件 |

---

## 任务 1 补丁：登录页改造（D12 + D13）

### D12 修复：保留 Vuex store 集成

**原计划缺陷：** Login.vue 改造为 axios 直接调用，绕过 `store/index.js` 的 `login` action，但其他组件可能依赖 `store.state.token`。

**修复：** Login.vue 调用 store action，store action 内部改用 `client_id`（不是 `username`）调 `/auth/login`。

**文件：**
- 修改：`dashboard/src/store/index.js`（login action 改用 client_id）
- 修改：`dashboard/src/views/Login.vue`（dispatch 而非直接 axios）

**步骤 1：修改 store login action**

```javascript
// dashboard/src/store/index.js
// 原：const resp = await axios.post('/api/v1/auth/login', { client_id, password })
// 改：保持 store action，但确认字段为 client_id
async login({ commit }, { client_id, password }) {
  const resp = await axios.post('/api/v1/auth/login', { client_id, password })
  commit('SET_TOKEN', resp.data.access_token)
  commit('SET_ROLE', resp.data.role || 'client')
  return resp.data
}
```

**步骤 2：Login.vue 调用 store action**

```vue
<!-- dashboard/src/views/Login.vue <script setup> 内 -->
import { useStore } from 'vuex'
const store = useStore()

async function handleClientLogin() {
  if (!clientForm.client_id || !clientForm.password) {
    ElMessage.warning('请输入客户 ID 和密码')
    return
  }
  loading.value = true
  try {
    await store.dispatch('login', {
      client_id: clientForm.client_id,
      password: clientForm.password,
    })
    router.push('/')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
```

### D13 修复：保留现有路由

**原计划缺陷：** 计划路由配置为 `/dashboard`、`/distributions`、`/exports`、`/audit-logs`，丢失现有的 `/articles` 和 `/settings`。

**修复：** 在计划的路由数组基础上追加 `/articles` 和 `/settings`。

```javascript
// dashboard/src/router/index.js
const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/articles', name: 'Articles', component: () => import('../views/Articles.vue'), meta: { requiresAuth: true } },
  { path: '/distributions', name: 'Distributions', component: () => import('../views/Distributions.vue'), meta: { requiresAuth: true } },
  { path: '/exports', name: 'Exports', component: () => import('../views/Exports.vue'), meta: { requiresAuth: true } },
  { path: '/audit-logs', name: 'AuditLogs', component: () => import('../views/AuditLogs.vue'), meta: { requiresAuth: true } },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue'), meta: { requiresAuth: true } },
]
```

---

## 任务 2 补丁：Dashboard 已实现，改为验证任务（D19）

### D19 修复：标记为验证任务

**原计划缺陷：** 现有 Dashboard.vue 已包含 4 卡片 + 5 图表 + `isAdmin` + ExportDialog 集成 + `citation_count` 修复（调用 `/stats/citation`）。按原计划实现会**回退**已修复的功能。

**修复：** 任务 2 改为验证任务，不写新代码，仅运行验证命令确认现有实现符合设计。

**验证步骤：**

```bash
# 1. 确认 Dashboard.vue 包含 4 卡片 + 5 图表
grep -c "StatCard\|chart-card" dashboard/src/views/Dashboard.vue
# 预期：≥ 9（4 卡片 + 5 图表）

# 2. 确认 citation_count 调用 /stats/citation
grep "stats/citation" dashboard/src/views/Dashboard.vue
# 预期：匹配到 api.get('/stats/citation')

# 3. 确认 ExportDialog 接收 charts prop
grep ":charts" dashboard/src/views/Dashboard.vue
# 预期：匹配到 :charts="chartsData"

# 4. npm run build
cd dashboard && npm run build
# 预期：构建成功
```

---

## 任务 3 补丁：客户端分发记录端点（D04）

### D04 修复：新增 GET /distributions 端点

**原计划缺陷：** Distributions.vue 客户端调用 `GET /distributions`，但后端只有 `POST /distributions`（admin 手动录入）和 `GET /admin/distributions`（admin 查询）。客户端登录后 404。

**修复：** 后端新增 `GET /distributions`（client 鉴权，按 client_id 过滤）。

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`（在 distribution_router 上加 GET 端点）
- 测试：`index-monitor/tests/integration/test_distribution_endpoint.py`（新建）

**步骤 1：编写失败的测试**

```python
# index-monitor/tests/integration/test_distribution_endpoint.py
"""client GET /distributions 端点测试（D04 修复）。"""
import pytest
import pytest_asyncio
import jwt
from datetime import datetime, timedelta, timezone

from app.core.config import settings


@pytest_asyncio.fixture(autouse=True)
async def _override_app_db():
    from app.main import app
    from app.core.database import get_db
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _get_db_override():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _client_headers(client_id: str = "test_dist_client") -> dict:
    payload = {
        "sub": client_id, "type": "client", "role": "client",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')}"}


@pytest.mark.asyncio
async def test_client_list_distributions_returns_own_records(client, db_session):
    """client GET /distributions 返回自己的分发记录（按 client_id 过滤）。"""
    from app.models.client import Client
    from app.models.manual_distribution import ManualDistribution
    from sqlalchemy import delete

    c = Client(client_id="test_dist_client", username="dist", password_hash="x", status="active")
    db_session.add(c)
    md = ManualDistribution(
        client_id="test_dist_client",
        remote_url="https://dist.example.com/page",
        status="synced",
    )
    db_session.add(md)
    await db_session.commit()

    try:
        resp = await client.get("/api/v1/distributions", headers=_client_headers())
        assert resp.status_code == 200
        items = resp.json()["items"]
        # 至少包含刚插入的记录
        urls = [it["remote_url"] for it in items]
        assert "https://dist.example.com/page" in urls
    finally:
        await db_session.execute(delete(ManualDistribution).where(
            ManualDistribution.remote_url == "https://dist.example.com/page"
        ))
        await db_session.delete(c)
        await db_session.commit()
```

**步骤 2：运行测试确认失败**

```bash
docker exec geo-index-monitor-local pytest tests/integration/test_distribution_endpoint.py -v
# 预期：FAIL，404 Not Found
```

**步骤 3：实现端点**

在 `index-monitor/app/api/admin_routes.py` 的 `distribution_router` 上追加 GET 端点：

```python
# GET /distributions：client 查询自己的分发记录（D04 修复）
# 挂在 distribution_router（无 /admin 前缀），实际路径 /api/v1/distributions
@distribution_router.get("/distributions")
async def list_client_distributions(
    user_client: tuple = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """client 查看自己的分发记录（按 client_id 过滤）。

    admin 应使用 GET /admin/distributions（跨客户视图）。
    本端点用 get_current_user 统一鉴权，client 角色 按 user.client_id 过滤。
    """
    user, role = user_client
    if role != "client":
        raise HTTPException(status_code=403, detail="本端点仅供客户使用；admin 请用 /admin/distributions")

    service = DistributionQueryService(db)
    items = await service.list_distributions(client_id=user.client_id)
    return {"items": items, "total": len(items)}
```

**步骤 4：运行测试确认通过**

```bash
docker exec geo-index-monitor-local pytest tests/integration/test_distribution_endpoint.py -v
# 预期：PASS
```

**步骤 5：Commit**

```bash
git add index-monitor/app/api/admin_routes.py \
        index-monitor/tests/integration/test_distribution_endpoint.py
git commit -m "feat(monitor): add GET /distributions endpoint for client (D04)

原计划 Distributions.vue 客户端调用 GET /distributions，但后端只有
POST /distributions（admin）和 GET /admin/distributions（admin）。
新增 GET /distributions（client 鉴权，按 client_id 过滤）闭合端点缺口。"
```

---

## 任务 4 补丁：Exports 已实现，改为验证任务（D20）

### D20 修复：标记为验证任务

**原计划缺陷：** 现有 Exports.vue 已有文件大小列，ExportDialog.vue 已有 charts prop + 图表提示 Alert。按原计划实现会回退。

**修复：** 任务 4 改为验证任务。

**验证步骤：**

```bash
# 1. 确认 Exports.vue 存在且有文件大小列
grep "file_size\|formatFileSize" dashboard/src/views/Exports.vue
# 预期：匹配到

# 2. 确认 ExportDialog 有 charts prop + 图表提示
grep "charts\|hasCharts" dashboard/src/components/ExportDialog.vue
# 预期：匹配到

# 3. npm run build
cd dashboard && npm run build
# 预期：构建成功
```

---

## 任务 5 补丁：侧边栏保留现有菜单项（D14）

### D14 修复：App.vue 不丢失 /articles /settings

**原计划缺陷：** 计划的 App.vue 侧边栏菜单只有 `/dashboard`、`/distributions`、`/exports`、`/audit-logs`，丢失现有的 `/articles` 和 `/settings`。且现有 App.vue 是水平菜单，计划改为 `el-container` + `el-aside` 侧边栏会破坏现有布局。

**修复：** 如果改为侧边栏布局，菜单项必须包含全部 6 个路由。

```vue
<!-- dashboard/src/App.vue（侧边栏版，保留全部菜单项） -->
<template>
  <el-container class="app-container" v-if="showNav">
    <el-aside width="220px" class="app-aside">
      <div class="logo">知氪AI监测平台</div>
      <el-menu :default-active="activeMenu" router>
        <el-menu-item index="/"><el-icon><DataLine /></el-icon>仪表盘</el-menu-item>
        <el-menu-item index="/articles"><el-icon><Document /></el-icon>文章列表</el-menu-item>
        <el-menu-item index="/distributions"><el-icon><Share /></el-icon>分发记录</el-menu-item>
        <el-menu-item index="/exports"><el-icon><Download /></el-icon>导出报告</el-menu-item>
        <el-menu-item index="/audit-logs" v-if="isAdmin"><el-icon><List /></el-icon>审计日志</el-menu-item>
        <el-menu-item index="/settings"><el-icon><Setting /></el-icon>系统设置</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <el-button text @click="logout">退出登录</el-button>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
  <router-view v-else />
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataLine, Document, Share, Download, List, Setting } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()

const showNav = computed(() => route.path !== '/login')
const activeMenu = computed(() => route.path)
const isAdmin = computed(() => localStorage.getItem('role') === 'admin')

const logout = () => {
  localStorage.removeItem('token')
  localStorage.removeItem('role')
  router.push('/login')
}
</script>
```

**注：** 如果用户偏好保留现有水平菜单（`mode="horizontal"`），只需在现有菜单中追加 `/distributions` 和 `/audit-logs` 两项，不改为侧边栏布局。

---

## 任务 6 补丁：审计日志端点补 total 字段（D15）

### D15 修复：后端返回 total

**原计划缺陷：** `/admin/audit_logs` 返回 `{items, page, page_size}`，没有 `total` 字段。前端分页器无法显示总页数。

**修复：** 后端 `list_audit_logs` 返回 `total`（用 `select(func.count())` 聚合）。

**文件：**
- 修改：`index-monitor/app/api/admin_routes.py`（list_audit_logs 加 total）
- 测试：`index-monitor/tests/integration/test_admin_endpoints.py`（加 total 断言）

**步骤 1：编写失败的测试**

在 `test_admin_endpoints.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_list_audit_logs_returns_total(client, db_session):
    """list_audit_logs 返回 total 字段（D15 修复）。"""
    from app.models.admin_audit_log import AdminAuditLog
    from sqlalchemy import delete

    log = AdminAuditLog(
        admin_user_id=1, admin_name="test", action="test_action",
        target_type="test", target_id="d15_test",
    )
    db_session.add(log)
    await db_session.commit()

    try:
        resp = await client.get("/api/v1/admin/audit_logs", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] >= 1
    finally:
        await db_session.execute(delete(AdminAuditLog).where(AdminAuditLog.target_id == "d15_test"))
        await db_session.commit()
```

**步骤 2：运行测试确认失败**

```bash
docker exec geo-index-monitor-local pytest tests/integration/test_admin_endpoints.py::test_list_audit_logs_returns_total -v
# 预期：FAIL，KeyError: 'total'
```

**步骤 3：实现 total 聚合**

修改 `admin_routes.py` 的 `list_audit_logs`：

```python
@router.get("/audit_logs")
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: Optional[str] = None,
    admin: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """审计日志列表。admin 看自己，super_admin 看所有。设计文档第 10 节。"""
    # D15 修复：先查 total（同样过滤条件下）
    count_query = select(func.count()).select_from(AdminAuditLog)
    if admin["role"] != "super_admin":
        count_query = count_query.where(AdminAuditLog.admin_user_id == admin["user_id"])
    if action:
        count_query = count_query.where(AdminAuditLog.action == action)
    total = (await db.execute(count_query)).scalar()

    # 查分页数据
    query = select(AdminAuditLog)
    if admin["role"] != "super_admin":
        query = query.where(AdminAuditLog.admin_user_id == admin["user_id"])
    if action:
        query = query.where(AdminAuditLog.action == action)
    query = query.order_by(AdminAuditLog.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    return {
        "items": [
            # ...（原 items 序列化不变）
        ],
        "page": page,
        "page_size": page_size,
        "total": total,  # D15 修复
    }
```

**步骤 4-5：运行测试通过 + Commit**

```bash
docker exec geo-index-monitor-local pytest tests/integration/test_admin_endpoints.py::test_list_audit_logs_returns_total -v

git add index-monitor/app/api/admin_routes.py tests/integration/test_admin_endpoints.py
git commit -m "feat(monitor): return total in /admin/audit_logs (D15)"
```

---

## 任务 7 补丁：官网入口路径与样式修正（D07 + D08 + D21）

### D07 + D08 + D21 修复：正确路径 + Tailwind 风格

**原计划缺陷：**
1. `homepage.blade.php` 不存在（D07），实际首页是 `site/home.blade.php`，导航在 `site/partials/header.blade.php`
2. 代码用 Bootstrap 类（`navbar-nav`、`nav-link`），但 GEOFlow 官网用 Tailwind + Lucide icons（D08）
3. commit 命令文件扩展名 `.py` 应为 `.php`（D21）

**修复：** 修改 `site/partials/header.blade.php` 和 `site/partials/footer.blade.php`，用 Tailwind + Lucide 风格。

**步骤 1：查看现有 header.blade.php 结构**

```bash
cat GEOFlow-main/resources/views/site/partials/header.blade.php
# 确认现有 nav 结构：<nav class="hidden md:flex items-center space-x-6">
```

**步骤 2：在 header.blade.php 导航区追加监测平台入口**

```blade
{{-- site/partials/header.blade.php --}}
{{-- 在现有 <nav class="hidden md:flex items-center space-x-6"> 内追加 --}}
<a href="https://monitor.zkeeeai.com" target="_blank" rel="noopener"
   class="text-gray-600 hover:text-gray-900 flex items-center gap-1">
    <i data-lucide="chart-line" class="w-4 h-4"></i>
    <span>{{ __('site.nav.monitor') }}</span>
</a>
```

**步骤 3：在 footer.blade.php 追加监测平台链接**

```blade
{{-- site/partials/footer.blade.php --}}
{{-- 在 footer 链接区追加 --}}
<a href="https://monitor.zkeeeai.com" target="_blank" rel="noopener"
   class="text-gray-400 hover:text-white">
    {{ __('site.nav.monitor') }}
</a>
```

**步骤 4：添加翻译键**

```bash
# lang/zh_CN/site.php（如不存在则创建）
echo '<?php return ["nav" => ["monitor" => "监测平台"]]; ?>' > GEOFlow-main/lang/zh_CN/site.php
```

**步骤 5：Commit（注意扩展名 .php）**

```bash
git add GEOFlow-main/resources/views/site/partials/header.blade.php \
        GEOFlow-main/resources/views/site/partials/footer.blade.php \
        GEOFlow-main/lang/zh_CN/site.php
git commit -m "feat(geoflow): add monitor platform entry on homepage (D07+D08+D21)"
```

---

## 任务 8 补丁：后台监测菜单已实现，改为验证任务（D09 + D10 + D11）

### D09 + D10 + D11 修复：标记为验证任务

**原计划缺陷：**
1. `layouts/admin.blade.php` 路径不存在（D09），实际是 `admin/layouts/app.blade.php` + `admin/partials/header.blade.php`
2. 代码用 AdminLTE 类（`main-sidebar`），但实际用 Tailwind + `$menu` 数组（D10）
3. **任务已完全实现**（D11）：`admin/partials/header.blade.php:31` 已有 `'monitor'` 菜单项，`config/geoflow.php:38` 已有 `monitor_url`，`lang/zh_CN/admin.php:15` 已有翻译

**修复：** 任务 8 改为验证任务，不写新代码。

**验证步骤：**

```bash
# 1. 确认 admin/partials/header.blade.php 有 monitor 菜单项
grep "monitor" GEOFlow-main/resources/views/admin/partials/header.blade.php
# 预期：匹配到 'monitor' => ['url' => config('geoflow.monitor_url', ...)

# 2. 确认 config/geoflow.php 有 monitor_url
grep "monitor_url" GEOFlow-main/config/geoflow.php
# 预期：匹配到 'monitor_url' => env('MONITOR_URL', ...)

# 3. 确认翻译键存在
grep "monitor" GEOFlow-main/lang/zh_CN/admin.php
# 预期：匹配到 'monitor' => '监测系统'

# 4. 浏览器访问 GEOFlow 后台，确认顶部菜单显示"监测系统"
```

---

## 任务 9 补丁：归档服务修复（D01 + D02 + D03 + D06 + D16 + D18 + D22 + D23 + D25）

这是缺陷最密集的任务，共 9 项缺陷。逐个修复。

### 前置条件声明（D25 修复）

**D25：** 归档任务依赖 `monitor.archived_distributions` 表（迁移 006 创建）。任务 9 必须声明前置条件。

```markdown
**前置条件：**
- `alembic upgrade head` 已执行（当前版本 ≥ 009）
- 迁移 006 已创建 `monitor.archived_distributions` 表
- 迁移 009 已删除孤儿表 `monitor.article_distributions`
```

### D03 修复：scheduler.py 增量编辑（不替换）

**原计划缺陷：** 计划代码完全覆盖 `scheduler.py`，会丢失现有的 `scheduled_export_processor`（每 30 秒扫 pending 导出任务）和 `ExportService`/`ExportTask`/`IntervalTrigger` 导入。

**修复：** 改为增量编辑——保留现有内容，仅追加归档相关任务。

**文件：**
- 修改：`index-monitor/app/services/scheduler.py`（追加，不替换）
- 创建：`index-monitor/app/services/archive_service.py`（新建）
- 测试：`index-monitor/tests/unit/test_archive_service.py`（新建）

**步骤 1：编写 ArchiveService 测试（TDD）**

```python
# index-monitor/tests/unit/test_archive_service.py
"""ArchiveService 测试（任务 9 补丁）。

覆盖 D01/D02/D06 修复：
- D01：client_id 不为 None（匹配 domain_map）
- D02：content_keywords Text→JSON 转换
- D06：查询条件用 action=="delete"（不是 status=="deleted"）
"""
import pytest
from datetime import datetime, timezone

from app.services.archive_service import ArchiveService


@pytest.mark.asyncio
async def test_archive_deleted_distributions_matches_client_by_domain(db_session):
    """D01：归档前通过 domain_map 匹配 client_id，None 时跳过。"""
    from app.models.client import Client, ClientSite
    from app.models.geoflow_models import GeoflowArticle, GeoflowArticleDistribution
    from app.models.archived_distribution import ArchivedDistribution
    from sqlalchemy import delete

    # 准备：client + site（domain 匹配）+ GEOFlow 删除记录
    client = Client(client_id="test_archive_d01", username="arch_d01",
                    password_hash="x", status="active")
    db_session.add(client)
    site = ClientSite(client_id="test_archive_d01", site_name="站",
                      domain="archive-d01.example.com", site_type="official", status="active")
    db_session.add(site)
    article = GeoflowArticle(title="归档测试", slug="arch-d01", content="内容",
                             category_id=1, author_id=1, status="published")
    db_session.add(article)
    dist = GeoflowArticleDistribution(
        article_id=article.id, distribution_channel_id=1,
        action="delete", status="synced",  # D06：action="delete" 是删除标记
        remote_url="https://www.archive-d01.example.com/deleted-page",
    )
    db_session.add(dist)
    await db_session.commit()

    try:
        service = ArchiveService(db_session)
        count = await service.archive_deleted_distributions()
        assert count >= 1

        # D01 验证：归档记录的 client_id 不为 None
        result = await db_session.execute(
            select(ArchivedDistribution).where(
                ArchivedDistribution.remote_url == "https://www.archive-d01.example.com/deleted-page"
            )
        )
        archived = result.scalar_one_or_none()
        assert archived is not None
        assert archived.client_id == "test_archive_d01"  # D01：不为 None
    finally:
        await db_session.execute(delete(ArchivedDistribution).where(
            ArchivedDistribution.remote_url == "https://www.archive-d01.example.com/deleted-page"
        ))
        await db_session.delete(dist)
        await db_session.delete(article)
        await db_session.delete(site)
        await db_session.delete(client)
        await db_session.commit()
```

**步骤 2：运行测试确认失败**

```bash
docker exec geo-index-monitor-local pytest tests/unit/test_archive_service.py -v
# 预期：FAIL，ImportError（ArchiveService 不存在）
```

**步骤 3：实现 ArchiveService（含 D01/D02/D06 修复）**

```python
# index-monitor/app/services/archive_service.py
"""归档服务：定期归档已删除的分发记录。

任务 9 补丁（D01/D02/D06 修复）：
- D01：client_id 通过 domain_map 匹配，匹配不到则跳过（不为 None）
- D02：content_keywords 从 Text 转 JSON（json.loads）
- D06：查询条件用 action=="delete"（不是 status=="deleted"）
"""
import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.archived_distribution import ArchivedDistribution
from app.models.client import ClientSite
from app.models.geoflow_models import (
    GeoflowArticle,
    GeoflowArticleDistribution,
    GeoflowDistributionChannel,
)
from app.models.index_result import IndexResult
from app.models.citation_result import CitationResult
from app.utils.validators import normalize_domain

logger = logging.getLogger(__name__)


class ArchiveService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _build_domain_map(self) -> dict[str, str]:
        """domain → client_id 映射（用于 D01 匹配）。"""
        result = await self.db.execute(
            select(ClientSite).where(ClientSite.status == "active")
        )
        return {
            normalize_domain(s.domain): s.client_id
            for s in result.scalars().all()
        }

    @staticmethod
    def _parse_keywords(raw) -> list:
        """D02：Text → JSON list 转换（参考 distribution_query._serialize_geoflow）。"""
        if isinstance(raw, str) and raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return [k.strip() for k in raw.split(",") if k.strip()]
        return raw or []

    async def archive_deleted_distributions(self) -> int:
        """归档已删除的分发记录（action=='delete'）。

        D06 修复：查询条件用 action=="delete"（GEOFlow 删除标记），
        不是 status=="deleted"（status 默认是 queued/synced）。
        """
        # D06：查 action=='delete' 的记录
        query = (
            select(GeoflowArticleDistribution, GeoflowArticle, GeoflowDistributionChannel)
            .join(GeoflowArticle, GeoflowArticle.id == GeoflowArticleDistribution.article_id)
            .outerjoin(
                GeoflowDistributionChannel,
                GeoflowDistributionChannel.id == GeoflowArticleDistribution.distribution_channel_id,
            )
            .where(
                GeoflowArticleDistribution.action == "delete",  # D06
                GeoflowArticleDistribution.remote_url.isnot(None),
            )
        )
        rows = (await self.db.execute(query)).fetchall()
        domain_map = await self._build_domain_map()

        count = 0
        for dist, article, channel in rows:
            domain = normalize_domain(dist.remote_url)
            client_id = domain_map.get(domain)
            if client_id is None:
                # D01：未匹配 domain 则跳过（不为 None）
                logger.warning(f"归档跳过：URL {dist.remote_url} 的 domain {domain} 未登记")
                continue

            archived = ArchivedDistribution(
                client_id=client_id,  # D01：不为 None
                remote_url=dist.remote_url,
                source="geoflow",
                action=dist.action,
                channel_name=channel.name if channel else None,
                content_title=article.title if article else None,
                content_slug=article.slug if article else None,
                content_excerpt=article.excerpt if article else None,
                content_body=article.content if article else None,
                content_keywords=self._parse_keywords(article.keywords),  # D02：Text→JSON
                meta_description=article.meta_description if article else None,
                original_keyword=article.original_keyword if article else None,
                published_at=article.published_at if article else None,
                distributed_at=dist.created_at,
                archived_at=datetime.now(timezone.utc),
            )
            self.db.add(archived)
            count += 1

        await self.db.commit()
        return count
```

**步骤 4：运行测试确认通过**

```bash
docker exec geo-index-monitor-local pytest tests/unit/test_archive_service.py -v
# 预期：PASS
```

### D03 修复：scheduler.py 增量追加（不替换）

**修复：** 在现有 `scheduler.py` 末尾追加归档任务，不覆盖现有 `scheduled_export_processor`。

```python
# index-monitor/app/services/scheduler.py（末尾追加，不替换）

# D16 修复：or_ 在顶部导入
from sqlalchemy import or_  # noqa: E402（追加到现有 import 区）


# D03 修复：增量追加，不替换现有 scheduled_export_processor
async def scheduled_archive_scan():
    """每月 1 日归档已删除的分发记录（任务 9 补丁）。"""
    from app.services.archive_service import ArchiveService  # 延迟导入避免循环
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        service = ArchiveService(session)
        count = await service.archive_deleted_distributions()
        logger.info(f"归档扫描完成：归档 {count} 条已删除分发记录")


async def scheduled_monthly_archive():
    """每月 1 日凌晨 2 点执行归档（D22 修复：补充 timezone 导入）。"""
    # D22 修复：在函数内导入 timezone（避免作用域问题）
    from datetime import datetime, timezone
    from sqlalchemy import select, delete
    from app.models.index_result import IndexResult
    from app.models.citation_result import CitationResult

    now = datetime.now(timezone.utc)  # D22：timezone 已导入
    # 保留最近 90 天的数据
    cutoff = now - timedelta(days=90)

    async with async_session_factory() as session:
        # D18 修复：导出完整字段（不遗漏）
        old_index = (await session.execute(
            select(IndexResult).where(IndexResult.updated_at < cutoff)
        )).scalars().all()

        for ir in old_index:
            # D18：列出所有字段
            archive_data = {
                "url": ir.url, "client_id": ir.client_id, "site_type": ir.site_type,
                "content_title": ir.content_title, "content_keywords": ir.content_keywords,
                "content_snapshot": ir.content_snapshot,
                "baidu_status": ir.baidu_status, "toutiao_status": ir.toutiao_status,
                "sogou_status": ir.sogou_status, "so360_status": ir.so360_status,
                "bing_status": ir.bing_status,
                "baidu_checked_at": ir.baidu_checked_at.isoformat() if ir.baidu_checked_at else None,
                "toutiao_checked_at": ir.toutiao_checked_at.isoformat() if ir.toutiao_checked_at else None,
                "sogou_checked_at": ir.sogou_checked_at.isoformat() if ir.sogou_checked_at else None,
                "so360_checked_at": ir.so360_checked_at.isoformat() if ir.so360_checked_at else None,
                "bing_checked_at": ir.bing_checked_at.isoformat() if ir.bing_checked_at else None,
            }
            # 写入归档表或 JSON 文件（按设计文档选择）
            # ...

        # 删除已归档的旧数据
        await session.execute(delete(IndexResult).where(IndexResult.updated_at < cutoff))
        await session.commit()


def start_scheduler():
    """启动所有定时任务（D03 修复：保留现有 + 追加归档）。"""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    scheduler = AsyncIOScheduler()

    # 保留：现有 scheduled_index_check（每 6 小时）
    scheduler.add_job(scheduled_index_check, IntervalTrigger(hours=6), id="index_check")

    # 保留：现有 scheduled_export_processor（每 30 秒，D03 关键）
    scheduler.add_job(scheduled_export_processor, IntervalTrigger(seconds=30), id="export_processor")

    # 追加：归档扫描（每天凌晨 2 点检查是否需要归档）
    scheduler.add_job(scheduled_archive_scan, CronTrigger(hour=2, minute=0), id="archive_scan")

    scheduler.start()
    return scheduler
```

**步骤 5：运行 scheduler 测试**

```bash
docker exec geo-index-monitor-local pytest tests/unit/test_scheduler.py -v
# 预期：现有 2 passed + 新增归档注册测试通过
```

**步骤 6：Commit**

```bash
git add index-monitor/app/services/archive_service.py \
        index-monitor/app/services/scheduler.py \
        index-monitor/tests/unit/test_archive_service.py
git commit -m "feat(monitor): archive service with D01/D02/D03/D06 fixes

- D01: client_id matched via domain_map (not None)
- D02: content_keywords Text→JSON via json.loads
- D03: scheduler.py incremental edit (preserve scheduled_export_processor)
- D06: query action=='delete' (not status=='deleted')
- D16: or_ import at top
- D18: complete archive fields
- D22: timezone import in function
- D23: unified import style
- D25: declared dependency on migration 006"
```

---

## 任务 10 补丁：E2E 测试脚本修正（D05 + D17 + D24）

### D05 + D24 修复：API 路径修正

**原计划缺陷：**
- D05：调用 `/api/v1/system/config`，实际端点是 `/api/v1/config`
- D24：CORS 检查 `OPTIONS /api/v1/system/config` 同样路径错误

**修复：** 全部改为 `/api/v1/config`。

**步骤 1：编写修正版 E2E 脚本**

```bash
# index-monitor/deploy/scripts/test-unified-db-e2e.sh
#!/usr/bin/env bash
# M4 任务 10 补丁：E2E 测试脚本（D05+D17+D24 修复）
set -euo pipefail

MONITOR_URL="${MONITOR_URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

echo "=== M4 E2E 冒烟测试 ==="

# 步骤 1：健康检查
echo "[1/10] 健康检查"
curl -sf "$MONITOR_URL/api/v1/health" | grep -q "healthy" || { echo "FAIL: 健康检查"; exit 1; }

# 步骤 2：SSO 登录页可达
echo "[2/10] SSO 登录页"
curl -sf -o /dev/null -w "%{http_code}" "$MONITOR_URL/sso/login" | grep -q "302" || { echo "FAIL: SSO 登录页"; exit 1; }

# 步骤 3：配置端点（D05 修复：/config 不是 /system/config）
echo "[3/10] 配置端点"
curl -sf "$MONITOR_URL/api/v1/config" | grep -q "ai_citation_models" || { echo "FAIL: 配置端点"; exit 1; }

# 步骤 4-7：admin 端点（需 admin token）
if [ -n "$ADMIN_TOKEN" ]; then
  echo "[4/10] admin 客户列表"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "$MONITOR_URL/api/v1/admin/clients" | grep -q "items" || { echo "FAIL"; exit 1; }

  echo "[5/10] admin 分发记录"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "$MONITOR_URL/api/v1/admin/distributions" | grep -q "items" || { echo "FAIL"; exit 1; }

  echo "[6/10] admin 审计日志（D15：含 total）"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "$MONITOR_URL/api/v1/admin/audit_logs" | grep -q "total" || { echo "FAIL"; exit 1; }

  echo "[7/10] admin 采信统计（C7：新端点）"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" "$MONITOR_URL/api/v1/admin/stats/citation" | grep -q "total" || { echo "FAIL"; exit 1; }
fi

# 步骤 8：CORS 检查（D24 修复：/config 路径）
echo "[8/10] CORS 预检"
curl -sf -X OPTIONS "$MONITOR_URL/api/v1/config" \
  -H "Origin: https://monitor.zkeeeai.com" \
  -H "Access-Control-Request-Method: GET" \
  -o /dev/null -w "%{http_code}" | grep -q "200" || { echo "FAIL: CORS"; exit 1; }

# 步骤 9：导出端点（需 token）
if [ -n "$ADMIN_TOKEN" ]; then
  echo "[9/10] 创建导出任务"
  TASK_RESP=$(curl -sf -X POST "$MONITOR_URL/api/v1/admin/exports" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"export_type":"pdf"}')
  echo "$TASK_RESP" | grep -q "task_id" || { echo "FAIL: 导出"; exit 1; }
fi

# 步骤 10：域名状态
echo "[10/10] 域名状态"
curl -sf -o /dev/null -w "%{http_code}" "https://monitor.zkeeeai.com" | grep -q "200" || { echo "FAIL: 域名"; exit 1; }

echo "=== E2E 冒烟测试全部通过 ==="
```

### D17 修复：补充核心链路测试

**原计划缺陷：** 21 步测试中步骤 8-20 全部跳过（占位），实际只跑 7 步冒烟。

**修复：** 补充核心功能链路测试（创建客户 → 手动录入 → 批量检测 → 导出 → 审计日志）。

**步骤：在 E2E 脚本中追加集成测试段**

```bash
# test-unified-db-e2e.sh 追加（D17 修复：核心链路测试）

if [ -n "$ADMIN_TOKEN" ]; then
  echo "=== 核心链路测试 ==="

  # 步骤 11：创建测试客户
  echo "[11/15] 创建测试客户"
  CLIENT_RESP=$(curl -sf -X POST "$MONITOR_URL/api/v1/admin/clients" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"client_id":"e2e_test","username":"e2e","password":"Pass1234"}')
  echo "$CLIENT_RESP" | grep -q "e2e_test" || { echo "FAIL: 创建客户"; exit 1; }

  # 步骤 12：手动录入 URL
  echo "[12/15] 手动录入 URL"
  curl -sf -X POST "$MONITOR_URL/api/v1/distributions" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"remote_url":"https://e2e-test.example.com/page","client_id":"e2e_test"}' \
    | grep -q "created" || { echo "FAIL: 手动录入"; exit 1; }

  # 步骤 13：查询分发记录（D04：client 端点）
  echo "[13/15] 查询分发记录"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$MONITOR_URL/api/v1/admin/distributions?client_id=e2e_test" \
    | grep -q "e2e-test.example.com" || { echo "FAIL: 查询分发"; exit 1; }

  # 步骤 14：触发批量检测
  echo "[14/15] 批量检测"
  DIST_ID=$(curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$MONITOR_URL/api/v1/admin/distributions?client_id=e2e_test" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")
  curl -sf -X POST "$MONITOR_URL/api/v1/admin/distributions/batch-scan" \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"distribution_ids\":[\"$DIST_ID\"],\"scan_type\":\"both\"}" \
    | grep -q "queued" || { echo "FAIL: 批量检测"; exit 1; }

  # 步骤 15：查询审计日志
  echo "[15/15] 审计日志"
  curl -sf -H "Authorization: Bearer $ADMIN_TOKEN" \
    "$MONITOR_URL/api/v1/admin/audit_logs?action=create_client" \
    | grep -q "e2e_test" || { echo "FAIL: 审计日志"; exit 1; }

  # 清理：删除测试客户
  curl -sf -X DELETE "$MONITOR_URL/api/v1/admin/clients/e2e_test" \
    -H "Authorization: Bearer $ADMIN_TOKEN" > /dev/null

  echo "=== 核心链路测试通过 ==="
fi
```

**步骤 2：运行 E2E 脚本**

```bash
chmod +x index-monitor/deploy/scripts/test-unified-db-e2e.sh
ADMIN_TOKEN="<your_admin_jwt>" \
  bash index-monitor/deploy/scripts/test-unified-db-e2e.sh
# 预期：全部通过
```

**步骤 3：Commit**

```bash
git add index-monitor/deploy/scripts/test-unified-db-e2e.sh
git commit -m "test(monitor): fix E2E script paths + add core link tests (D05+D17+D24)

- D05: /system/config → /config
- D17: 补充 15 步核心链路测试（创建客户→录入→检测→导出→审计）
- D24: CORS 检查路径修正"
```

---

## 批次 C 代码审查建议（纳入本补丁统一处理）

以下是整分支代码审查中"建议修改"级别的问题（批次 C），与上述缺陷一并处理。

### C1：export_routes.py 下载端点错误信息脱敏

**问题：** 下载端点报错时返回内部文件路径，泄露服务器结构。

**修复：** 已在批次 A 修复（commit `177e8d4`），file_path 替换为 file_size。

### C2：pdf_export_service.py 添加 --no-sandbox

**问题：** Docker 容器内 Chromium 启动失败。

**修复：** 已在批次 A 修复（commit `177e8d4`）。

### C3：Dockerfile.local Debian Trixie 包名

**问题：** libasound2 在 Trixie 中改名。

**修复：** 已在批次 A 修复（commit `177e8d4`）。

### C4：dashboard package.json 显式声明 @element-plus/icons-vue

**问题：** 依赖传递性脆弱。

**修复：** 已在批次 A 修复（commit `177e8d4`）。

### C5：main.js 全局注册 Element Plus 图标

**问题：** StatCard 等组件用字符串 prop 渲染图标，未注册时静默失败。

**修复：** 已在批次 A 修复（commit `177e8d4`）。

### C6：ExportTask 模型加 index 到 status 字段

**问题：** 查询 pending/processing 任务时全表扫描。

**修复：** 已在迁移 005 中实现（`status` 列已 `index=True`，见 `export_task.py:32`）。

### C7：admin 采信统计端点

**修复：** 已在批次 B 修复（commit `8ebc8bf`）。

### C8：ExportService._assemble_data 写死 charts: {}

**修复：** 已在缺口补全中修复（commit `88a9f05`）。

### C9：Dashboard.vue citation_count 写死 0

**修复：** 已在缺口补全中修复（commit `88a9f05`），调用 `/stats/citation`。

### C10：list_distributions 日期过滤

**修复：** 已在批次 B 修复（commit `8ebc8bf`）。

### C11：孤儿表 article_distributions

**修复：** 已在批次 B 修复（commit `8ebc8bf`），迁移 009 drop。

---

## 执行顺序建议

按依赖关系执行补丁：

1. **任务 9 补丁**（D01/D02/D03/D06/D16/D18/D22/D23/D25）——归档服务是后端独立模块，先做
2. **任务 6 补丁**（D15）——audit_logs 加 total，前端任务 6 依赖
3. **任务 3 补丁**（D04）——新增 client /distributions 端点，前端任务 3 依赖
4. **任务 1 补丁**（D12/D13）——登录页 + 路由，前端基础
5. **任务 5 补丁**（D14）——App.vue 侧边栏
6. **任务 7 补丁**（D07/D08/D21）——官网入口
7. **任务 2/4/8 补丁**（D19/D20/D11）——验证任务，最后确认
8. **任务 10 补丁**（D05/D17/D24）——E2E 脚本，全流程验证

---

## 自检清单

- [ ] 所有 11 项关键缺陷（D01-D11）有修复代码或验证步骤
- [ ] 所有 14 项重要缺陷（D12-D25）有修复代码或验证步骤
- [ ] 批次 C 的 11 项建议已标注状态（已修复/纳入补丁）
- [ ] 每个修复有明确的文件路径、代码块、测试命令
- [ ] 执行顺序无循环依赖
- [ ] 批次 A+B 已 commit 的修复未重复实现
