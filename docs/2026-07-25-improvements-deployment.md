# 两项改进部署指南（SSO CSRF state + 跨 schema DB 层权限隔离）

**日期：** 2026-07-25
**分支：** 主仓库 `feat/rebrand-dual-domain` / GEOFlow-main `main`
**适用：** 生产服务器 124.220.33.188

---

## 0. 改进概览

| 改进 | 目标 | 涉及仓库 | Commits |
|---|---|---|---|
| 改进 1：SSO CSRF state | 防登录 CSRF（state 一次性消费） | 主仓库 + GEOFlow-main | `7ae0381` + `98f0fb8` |
| 改进 2：DB 层权限隔离 | monitor_user 对 public 只读 / monitor 读写 | 主仓库 | `51f4730` + `9de0713` |

**本地测试状态：** 104 passed, 1 skipped（监测系统全量）+ GEOFlow 19/19 通过。无回归。

**两项改进相互独立**：SSO 走 Redis + HTTP（不触 DB），DB 隔离走 PG 连接用户。可分别启用。

---

## 1. 前置条件

- [ ] 主仓库 `feat/rebrand-dual-domain` 已 push 到远程
- [ ] GEOFlow-main `main` 已 push 到远程
- [ ] 生产服务器可 SSH（`SERVER_USER@SERVER_IP`，见 .env.prod）
- [ ] 生产 PG（`geoflow-postgres-prod`）运行中，`geo_user` 密码已知
- [ ] 生产 Redis 运行中（改进 1 依赖，已部署则跳过）

**push 命令**（本地执行）：
```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git push origin feat/rebrand-dual-domain
cd GEOFlow-main
git push origin main
```

---

## 2. 部署步骤

### 步骤 1：服务器拉取代码

```bash
ssh $SERVER_USER@$SERVER_IP
cd /opt/GEO-FLOW-LUMORA-CITE   # 或实际部署路径

# 主仓库
git fetch origin
git checkout feat/rebrand-dual-domain
git pull origin feat/rebrand-dual-domain

# GEOFlow-main（改进 1 state 透传）
cd GEOFlow-main
git pull origin main
cd ..
```

### 步骤 2：执行 DB 角色隔离脚本（改进 2）

> 此步骤创建 `monitor_user` 角色 + 授权。**幂等，可重复执行。**

```bash
cd /opt/GEO-FLOW-LUMORA-CITE

# 生成一个强密码（建议 32 字符随机串）
MONITOR_PASS=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
echo "monitor_user 密码: $MONITOR_PASS"
# ⚠️ 记下此密码，步骤 3 要用

# 执行脚本（连接生产 PG）
PGHOST=geoflow-postgres-prod \
PGUSER=geo_user \
PGPASSWORD=<geo_user 生产密码> \
PGDATABASE=geo_flow \
MONITOR_DB_PASSWORD=$MONITOR_PASS \
bash deploy/scripts/setup-db-roles.sh
```

**预期输出：**
```
=== 创建 DB 角色: monitor_user @ geoflow-postgres-prod:5432/geo_flow ===
    ✓ 已创建角色 monitor_user（LOGIN）
    ✓ 密码已设置
    ✓ public schema: USAGE + SELECT（只读）
    ✓ monitor schema: USAGE + ALL ON TABLES/SEQUENCES（读写）
    ✓ ALTER DEFAULT PRIVILEGES 已配置
=== 完成 ===
```

**验证角色创建成功**（可选）：
```bash
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -tAc \
  "SELECT has_table_privilege('monitor_user', 'public.articles', 'SELECT');"
# 应返回 t（true）
```

### 步骤 3：更新 .env.prod

```bash
cd /opt/GEO-FLOW-LUMORA-CITE

# 追加两行（用步骤 2 生成的密码）
echo "" >> .env.prod
echo "# DB 层权限隔离（改进 2）" >> .env.prod
echo "MONITOR_DB_USER=monitor_user" >> .env.prod
echo "MONITOR_DB_PASSWORD=$MONITOR_PASS" >> .env.prod

# 确认写入
grep MONITOR_DB .env.prod
```

### 步骤 4：重建并重启容器

```bash
cd /opt/GEO-FLOW-LUMORA-CITE

# GEOFlow（改进 1：authorize 透传 state）
cd GEOFlow-main
docker compose --env-file ../.env.prod -f docker-compose.prod.yml up -d --build web
cd ..

# 监测系统（改进 1 + 改进 2）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build index-monitor
```

**说明：**
- GEOFlow 只需重建 `web` 服务（SsoController 改动）；其余容器无改动。
- 监测系统重建 `index-monitor`（config.py + sso_routes.py + redis.py 改动）。
- Redis 容器无改动（改进 1 复用现有 Redis，仅新增 state key）。

### 步骤 5：验证

#### 5.1 确认 monitor_user 连接生效（改进 2）

```bash
docker exec geo-index-monitor python -c \
  "from app.core.config import settings; print(settings.DATABASE_URL)"
```
**预期：** URL 含 `monitor_user:...@geoflow-postgres-prod`（不含 `geo_user`）。

#### 5.2 SSO 端到端冒烟（改进 1）

```bash
cd /opt/GEO-FLOW-LUMORA-CITE
bash deploy/scripts/test-sso-e2e.sh
```
**预期：** 5 步全 ✅。

#### 5.3 功能冒烟

```bash
# 监测系统健康
curl -sk https://monitor.zkeeeai.com/ | head -5

# GEOFlow 官网
curl -sk https://zkeeeai.com/up
# 预期：200

# 监测系统登录页可访问
curl -sk -o /dev/null -w "%{http_code}" https://monitor.zkeeeai.com/
# 预期：200
```

#### 5.4 完整 SSO 流程手动验证

1. 浏览器访问 `https://monitor.zkeeeai.com/` → 跳转登录
2. 点击 SSO 登录 → 跳转 GEOFlow `https://zkeeeai.com/sso/authorize?...&state=...`
3. 若 GEOFlow 未登录 → 登录 admin → 自动回跳监测系统
4. 监测系统自动登录，显示 admin 信息，dashboard 正常加载
5. GEOFlow 现有功能（文章管理/分发）正常

---

## 3. 回滚方案

### 改进 2 回滚（DB 隔离）

**最快回滚**（不删角色，仅切回 geo_user）：
```bash
# .env.prod 注释掉两行
sed -i 's/^MONITOR_DB_USER=/#MONITOR_DB_USER=/' .env.prod
sed -i 's/^MONITOR_DB_PASSWORD=/#MONITOR_DB_PASSWORD=/' .env.prod
# 重启
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d index-monitor
```
monitor_user 角色保留无害（仅多一个无连接的角色）。

### 改进 1 回滚（SSO state）

**无需回滚**：state 参数向后兼容——GEOFlow authorize 不带 state 也能工作
（`test_authorize_without_state_still_works` 已验证）。若强行回滚，revert commit `7ae0381` + `98f0fb8`。

---

## 4. 验收清单

| # | 检查项 | 命令 / 方法 | 通过标准 |
|---|---|---|---|
| 1 | monitor_user 角色存在 | `psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='monitor_user'"` | 返回 1 |
| 2 | monitor_user 对 public 只读 | `has_table_privilege('monitor_user','public.articles','SELECT')` = t, `INSERT` = f | t / f |
| 3 | 应用用 monitor_user 连接 | `docker exec geo-index-monitor python -c "...settings.DATABASE_URL"` | URL 含 monitor_user |
| 4 | SSO E2E 冒烟 | `bash deploy/scripts/test-sso-e2e.sh` | 5 ✅ |
| 5 | 监测系统可访问 | `curl https://monitor.zkeeeai.com/` | 200 |
| 6 | GEOFlow 官网可访问 | `curl https://zkeeeai.com/up` | 200 |
| 7 | SSO 完整登录流程 | 浏览器手动 | 自动登录成功 |
| 8 | dashboard 数据正常 | 浏览器查看 | 跨 schema JOIN 数据可见 |

---

## 5. 注意事项

1. **执行顺序**：必须先跑 `setup-db-roles.sh`（步骤 2）再设 .env.prod（步骤 3）再重启（步骤 4）。
   若先重启容器而角色未创建，监测系统启动时会因 `monitor_user` 登录失败而连接报错。

2. **密码安全**：`MONITOR_DB_PASSWORD` 是生产密钥，勿提交到 git（.env.prod 已 gitignored）。
   建议用密码管理器记录。

3. **GEOFlow migration 后需重跑脚本**：若 GEOFlow 后续新增 public 表（migration），
   `ALTER DEFAULT PRIVILEGES` 已自动授权 SELECT 给 monitor_user，无需重跑。
   但若新增 monitor 表（alembic），同样自动授权 ALL。**仅在 monitor_user 权限异常时重跑脚本**。

4. **Redis 依赖**：改进 1 的 SSO state 存 Redis（TTL 300s）。若 Redis 宕机，SSO 登录会失败
  （callback 验证 state 时连接 Redis 报错）。需保障 Redis 可用（与 SSO code 同依赖）。

5. **向后兼容**：两项改进均向后兼容——
   - 改进 1：GEOFlow 不带 state 的旧流程仍工作；
   - 改进 2：不设 MONITOR_DB_USER 则继续用 geo_user。
