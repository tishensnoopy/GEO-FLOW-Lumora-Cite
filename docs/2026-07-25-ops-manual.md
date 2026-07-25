# 运维手册 — 知氪AI全链路监测平台

> **适用环境**：生产服务器 124.220.33.188（zkeeeai.com / monitor.zkeeeai.com）
> **最后更新**：2026-07-25
> **SSH 登录**：`ssh ubuntu@124.220.33.188`

---

## 一、系统架构概览

### 1.1 服务拓扑

```
                    ┌─────────────┐
   用户浏览器 ──────►│  geo-nginx  │:80/:443
                    │  (反向代理)  │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           ▼                               ▼
   zkeeeai.com                    monitor.zkeeeai.com
           │                               │
           ▼                       ┌───────┴───────┐
   ┌───────────────┐               ▼               ▼
   │ geoflow-web   │       ┌──────────────┐ ┌──────────────┐
   │ (GEOFlow官网) │       │geo-dashboard │ │geo-index     │
   │ :18080        │       │ (前端Vue)    │ │-monitor      │
   └───────┬───────┘       │ :80          │ │ (后端FastAPI)│
           │                └──────────────┘ │ :8090        │
           ▼                                  └──────┬───────┘
   ┌───────────────┐                               │
   │geoflow-app    │◄────── 跨 schema 查询 ────────┘
   │(Laravel PHP)  │
   ├───────────────┤
   │geoflow-       │
   │postgres-prod  │◄── 单一 PG 实例（public + monitor schema）
   │(pgvector:pg18)│
   ├───────────────┤
   │geoflow-redis  │
   │-prod (redis8) │
   └───────────────┘
```

### 1.2 容器清单（11 个运行 + 1 个已停用）

| 容器名 | 镜像 | 作用 | 所属栈 |
|--------|------|------|--------|
| geo-nginx | nginx:alpine | 双域名反向代理（zkeeeai.com + monitor.zkeeeai.com） | 监测系统 |
| geo-dashboard | geo-monitoring-dashboard | 监测系统前端（Vue 3） | 监测系统 |
| geo-index-monitor | geo-monitoring-index-monitor | 监测系统后端（FastAPI） | 监测系统 |
| geo-redis | redis:7-alpine | 监测系统 Redis（SSO state 存储） | 监测系统 |
| geoflow-web-prod | geoflow-web-prod | GEOFlow 官网 nginx | GEOFlow |
| geoflow-app-prod | geoflow-app-prod | GEOFlow Laravel 应用（php-fpm） | GEOFlow |
| geoflow-queue-prod | geoflow-app-prod | GEOFlow 队列处理器 | GEOFlow |
| geoflow-scheduler-prod | geoflow-app-prod | GEOFlow 定时任务 | GEOFlow |
| geoflow-reverb-prod | geoflow-app-prod | GEOFlow WebSocket 服务 | GEOFlow |
| geoflow-postgres-prod | pgvector/pgvector:pg18 | **统一数据库**（public + monitor schema） | GEOFlow |
| geoflow-redis-prod | redis:8-alpine | GEOFlow Redis | GEOFlow |
| ~~geo-postgres~~ | ~~postgres:15-alpine~~ | ~~旧监测系统 PG（已停用）~~ | 已废弃 |

### 1.3 关键目录

| 路径 | 说明 |
|------|------|
| `/opt/geo-monitoring/` | 监测系统代码（docker-compose.prod.yml + .env.prod） |
| `/opt/geoflow/` | GEOFlow 代码（docker-compose.prod.yml + .env.prod） |
| `/etc/letsencrypt/live/zkeeeai.com/` | zkeeeai.com SSL 证书 |
| `/etc/letsencrypt/live/monitor.zkeeeai.com/` | monitor.zkeeeai.com SSL 证书 |

### 1.4 数据库架构

```
单一 PostgreSQL（geoflow-postgres-prod，库名 geo_flow）
├── public schema（GEOFlow 读写，监测系统只读）
│   ├── articles, admins, article_distributions, distribution_channels ...
│   └── alembic_version（监测系统的迁移版本表）
└── monitor schema（监测系统读写）
    ├── clients, client_sites           ← 客户管理
    ├── article_distributions           ← 分发记录（监测系统自己的）
    ├── index_results, index_history    ← 收录检测
    ├── citation_results                ← AI 采信检测
    └── system_config                   ← 系统配置（含 AI API Key）
```

**DB 权限隔离**：
- `geo_user`：超级用户，GEOFlow 和 alembic 迁移使用
- `monitor_user`：监测系统专用，public 只读 / monitor 读写

---

## 二、查看日志

### 2.1 查看单个容器日志

```bash
# 监测系统后端（最常用）
docker logs geo-index-monitor --tail 50

# 监测系统前端
docker logs geo-dashboard --tail 50

# nginx 反向代理（查看请求/错误）
docker logs geo-nginx --tail 50

# GEOFlow 应用
docker logs geoflow-app-prod --tail 50

# GEOFlow 官网 nginx
docker logs geoflow-web-prod --tail 50
```

### 2.2 实时跟踪日志

```bash
# 实时跟踪监测系统后端日志（Ctrl+C 退出）
docker logs -f geo-index-monitor

# 同时跟踪多个容器日志（需要 tmux 或多终端）
docker logs -f geo-index-monitor &
docker logs -f geo-nginx &
```

### 2.3 查看指定时间段的日志

```bash
# 最近 10 分钟的日志
docker logs geo-index-monitor --since 10m

# 今天的日志
docker logs geo-index-monitor --since today

# 指定时间之后
docker logs geo-index-monitor --since "2026-07-25T12:00:00"
```

### 2.4 过滤错误日志

```bash
# 监测系统后端错误
docker logs geo-index-monitor 2>&1 | grep -i "error\|traceback\|exception" | tail -20

# nginx 错误（4xx/5xx）
docker logs geo-nginx 2>&1 | grep -E " (4[0-9]{2}|5[0-9]{2}) " | tail -20

# GEOFlow 应用异常
docker logs geoflow-app-prod 2>&1 | grep -i "error\|exception" | tail -20
```

### 2.5 查看数据库日志

```bash
# PostgreSQL 日志
docker logs geoflow-postgres-prod --tail 50

# 查看慢查询（如果开启了）
docker logs geoflow-postgres-prod 2>&1 | grep "duration:" | tail -10
```

---

## 三、重启服务

### 3.1 重启单个容器（不影响其他服务）

```bash
# 重启监测系统后端（最常用，改了代码后）
docker restart geo-index-monitor

# 重启监测系统前端
docker restart geo-dashboard

# 重启 nginx（改了 nginx 配置后）
docker exec geo-nginx nginx -t          # 先测试配置
docker exec geo-nginx nginx -s reload   # 热重载（不中断连接）
# 或完全重启：
# docker restart geo-nginx

# 重启 GEOFlow 应用
docker restart geoflow-app-prod
```

### 3.2 重启整个监测系统栈

```bash
cd /opt/geo-monitoring

# 重启所有监测系统容器（nginx + dashboard + index-monitor + redis）
docker compose --env-file .env.prod -f docker-compose.prod.yml restart

# 只重启某个服务
docker compose --env-file .env.prod -f docker-compose.prod.yml restart index-monitor
```

### 3.3 重新构建并启动（更新代码后）

```bash
cd /opt/geo-monitoring

# 重新构建镜像 + 重启容器（代码更新后使用）
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build index-monitor dashboard

# GEOFlow 代码更新后
cd /opt/geoflow
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build app
```

### 3.4 重启 GEOFlow 栈

```bash
cd /opt/geoflow

# 重启所有 GEOFlow 容器
docker compose --env-file .env.prod -f docker-compose.prod.yml restart

# 重启特定服务
docker compose --env-file .env.prod -f docker-compose.prod.yml restart app queue scheduler
```

---

## 四、检查健康状态

### 4.1 快速健康检查（一键脚本）

```bash
# 监测系统 API 健康
curl -s https://monitor.zkeeeai.com/api/v1/health
# 期望输出：{"status":"healthy"}

# GEOFlow 官网健康
curl -sI https://zkeeeai.com/up | head -1
# 期望输出：HTTP/2 200

# 监测系统 SSO 登录端点
curl -sI https://monitor.zkeeeai.com/sso/login | head -1
# 期望输出：HTTP/2 307（重定向）
```

### 4.2 容器状态检查

```bash
# 查看所有运行中的容器
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 检查是否有异常退出的容器
docker ps -a --filter "status=exited" --format "table {{.Names}}\t{{.Status}}"

# 查看容器资源使用
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"
```

### 4.3 数据库健康检查

```bash
# PG 容器健康
docker exec geoflow-postgres-prod pg_isready -U geo_user -d geo_flow
# 期望输出：accepting connections

# monitor_user 连接测试（验证权限隔离）
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -c \
  "SELECT has_table_privilege('monitor_user','monitor.clients','SELECT') AS can_read, \
          has_table_privilege('monitor_user','public.articles','SELECT') AS can_read_geoflow, \
          has_table_privilege('monitor_user','public.articles','INSERT') AS cannot_write_geoflow"
# 期望：can_read=t, can_read_geoflow=t, cannot_write_geoflow=f

# 监测系统数据概览
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -c \
  "SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname='monitor' ORDER BY relname"
```

### 4.4 系统资源检查

```bash
# 内存使用
free -h

# 磁盘使用
df -h /

# CPU 负载
uptime

# Docker 磁盘占用
docker system df
```

### 4.5 SSL 证书检查

```bash
# 查看证书有效期
echo | openssl s_client -connect zkeeeai.com:443 -servername zkeeeai.com 2>/dev/null \
  | openssl x509 -noout -dates

echo | openssl s_client -connect monitor.zkeeeai.com:443 -servername monitor.zkeeeai.com 2>/dev/null \
  | openssl x509 -noout -dates

# 测试证书续期（Let's Encrypt）
sudo certbot renew --dry-run
```

### 4.6 完整健康检查脚本

```bash
# 一键检查所有核心服务
echo "=== 容器状态 ==="
docker ps --format "{{.Names}}: {{.Status}}" | grep -E "geo-|geoflow-"

echo ""
echo "=== 公网访问 ==="
echo "monitor.zkeeeai.com: $(curl -s -o /dev/null -w '%{http_code}' -k https://monitor.zkeeeai.com/)"
echo "zkeeeai.com: $(curl -s -o /dev/null -w '%{http_code}' -k https://zkeeeai.com/)"

echo ""
echo "=== API 健康 ==="
curl -s https://monitor.zkeeeai.com/api/v1/health

echo ""
echo "=== 数据库 ==="
docker exec geoflow-postgres-prod pg_isready -U geo_user -d geo_flow

echo ""
echo "=== 资源 ==="
free -h | head -2
echo "磁盘: $(df -h / | tail -1 | awk '{print $4" free"}')"
```

---

## 五、常见问题排查

### 5.1 监测系统无法访问（monitor.zkeeeai.com 返回 502/503）

```bash
# 1. 检查 index-monitor 是否运行
docker ps | grep geo-index-monitor

# 2. 如果没运行，启动它
cd /opt/geo-monitoring
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d index-monitor

# 3. 查看启动日志找原因
docker logs geo-index-monitor --tail 30

# 4. 常见原因：数据库连接失败
#    检查 monitor_user 密码是否正确
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -c \
  "SELECT rolname FROM pg_roles WHERE rolname='monitor_user'"
```

### 5.2 SSO 登录失败

```bash
# 1. 测试 SSO 端点
curl -sI https://monitor.zkeeeai.com/sso/login
# 期望 307 重定向到 zkeeeai.com/sso/authorize

# 2. 测试 GEOFlow SSO 授权端点
curl -sI "https://zkeeeai.com/sso/authorize?redirect_uri=https://monitor.zkeeeai.com/sso/callback&state=test"
# 期望 302（未登录跳转登录页）

# 3. 检查 Redis（SSO state 存储）
docker exec geo-redis redis-cli -a $(grep REDIS_PASSWORD /opt/geo-monitoring/.env.prod | cut -d= -f2) ping
# 期望 PONG

# 4. 运行 SSO E2E 测试
cd /opt/geo-monitoring && bash deploy/scripts/test-sso-e2e.sh
```

### 5.3 数据库连接失败

```bash
# 1. 检查 PG 容器是否健康
docker exec geoflow-postgres-prod pg_isready -U geo_user -d geo_flow

# 2. 检查 monitor_user 密码
# 从 .env.prod 读取密码
MONITOR_PW=$(grep MONITOR_DB_PASSWORD /opt/geo-monitoring/.env.prod | cut -d= -f2)
# 测试连接
docker exec geoflow-postgres-prod psql \
  "host=localhost user=monitor_user password=${MONITOR_PW} dbname=geo_flow" \
  -c "SELECT 1"

# 3. 如果密码不匹配，重设
GEO_PW=$(grep DB_PASSWORD /opt/geoflow/.env.prod | cut -d= -f2)
docker exec -e PGPASSWORD="$GEO_PW" geoflow-postgres-prod psql -U geo_user -d geo_flow \
  -c "ALTER ROLE monitor_user WITH PASSWORD '$MONITOR_PW'"

# 4. 重启 index-monitor
docker restart geo-index-monitor
```

### 5.4 GEOFlow 官网无法访问

```bash
# 1. 检查 GEOFlow web 容器
docker ps | grep geoflow-web-prod

# 2. 检查 GEOFlow 应用
docker ps | grep geoflow-app-prod

# 3. 查看 GEOFlow 日志
docker logs geoflow-app-prod --tail 30

# 4. 测试内网访问
curl -s http://127.0.0.1:18080/up
```

### 5.5 SSL 证书过期

```bash
# 证书有效期检查
echo | openssl s_client -connect monitor.zkeeeai.com:443 -servername monitor.zkeeeai.com 2>/dev/null \
  | openssl x509 -noout -enddate

# 手动续期
sudo certbot renew

# 续期后重载 nginx
docker exec geo-nginx nginx -s reload

# 测试续期流程
sudo certbot renew --dry-run
```

### 5.6 磁盘空间不足

```bash
# 1. 查看磁盘使用
df -h /

# 2. 清理 Docker 无用镜像/容器/卷
docker system prune -a --volumes
# ⚠️ 谨慎：会删除所有未使用的镜像

# 3. 清理 Docker 构建缓存
docker builder prune -a

# 4. 清理旧日志
docker logs geo-index-monitor --tail 1000 > /tmp/last_logs.txt
truncate -s 0 $(docker inspect --format='{{.LogPath}}' geo-index-monitor)

# 5. 清理导出文件（如有）
ls -la /opt/geo-monitoring/data/exports/ 2>/dev/null
```

---

## 六、备份与回滚

### 6.1 数据库备份

```bash
# 备份 monitor schema（监测系统数据）
docker exec geoflow-postgres-prod pg_dump -U geo_user -d geo_flow \
  --schema=monitor --no-owner --no-acl > /tmp/monitor_backup_$(date +%Y%m%d).sql

# 备份 public schema（GEOFlow 数据）
docker exec geoflow-postgres-prod pg_dump -U geo_user -d geo_flow \
  --schema=public --no-owner --no-acl > /tmp/geoflow_backup_$(date +%Y%m%d).sql

# 完整备份
docker exec geoflow-postgres-prod pg_dump -U geo_user -d geo_flow \
  --no-owner --no-acl > /tmp/full_backup_$(date +%Y%m%d).sql
```

### 6.2 数据库恢复

```bash
# 恢复 monitor schema
docker exec -i geoflow-postgres-prod psql -U geo_user -d geo_flow \
  < /tmp/monitor_backup_20260725.sql
```

### 6.3 回滚到旧 PG（紧急情况）

如果统一数据库出现严重问题，可回滚到旧的独立 PG：

```bash
# 1. 启动旧 PG 容器
docker start geo-postgres

# 2. 修改 .env.prod
#    POSTGRES_HOST=postgres（改回旧值）
#    POSTGRES_DB=geo_monitoring（改回旧值）
#    删除或注释 MONITOR_DB_USER / MONITOR_DB_PASSWORD
sudo vi /opt/geo-monitoring/.env.prod

# 3. 重启监测系统
cd /opt/geo-monitoring
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
```

### 6.4 配置文件备份

```bash
# 备份关键配置
cp /opt/geo-monitoring/.env.prod /opt/geo-monitoring/.env.prod.bak.$(date +%Y%m%d)
cp /opt/geo-monitoring/docker-compose.prod.yml /opt/geo-monitoring/docker-compose.prod.yml.bak.$(date +%Y%m%d)
cp /opt/geo-monitoring/deploy/nginx/conf.d/default.conf /opt/geo-monitoring/deploy/nginx/conf.d/default.conf.bak.$(date +%Y%m%d)
```

---

## 七、日常运维任务

### 7.1 定期检查清单（建议每周一次）

- [ ] 容器状态：`docker ps` 所有容器 Up
- [ ] API 健康：`curl https://monitor.zkeeeai.com/api/v1/health`
- [ ] GEOFlow 健康：`curl -sI https://zkeeeai.com/up`
- [ ] SSL 证书有效期（过期前 30 天续期）
- [ ] 磁盘空间：`df -h /`（保持 20% 以上空闲）
- [ ] 内存：`free -h`（检查是否有 OOM）
- [ ] 错误日志：`docker logs geo-index-monitor 2>&1 | grep -i error | tail -10`
- [ ] 数据库备份：执行一次 `pg_dump`

### 7.2 更新代码部署

```bash
# 监测系统更新（从本地同步代码后）
cd /opt/geo-monitoring
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build index-monitor dashboard
docker exec geo-nginx nginx -s reload

# GEOFlow 更新（从本地同步代码后）
cd /opt/geoflow
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build app
```

### 7.3 查看/修改系统配置

```bash
# 查看当前系统配置（AI API Key 等）
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -c \
  "SELECT config_key, CASE WHEN config_value='' THEN '(空)' ELSE left(config_value,20)||'...' END AS value \
   FROM monitor.system_config ORDER BY config_key"

# 更新某个配置项（例如 DeepSeek API Key）
docker exec geoflow-postgres-prod psql -U geo_user -d geo_flow -c \
  "UPDATE monitor.system_config SET config_value='新密钥' WHERE config_key='ai_deepseek_api_key'"

# 修改后重启监测系统使配置生效
docker restart geo-index-monitor
```

---

## 八、紧急联系方式与参考文档

| 文档 | 路径 |
|------|------|
| 部署改进指南 | `docs/2026-07-25-improvements-deployment.md` |
| 设计规格文档 | `docs/superpowers/specs/2026-07-25-geoflow-monitor-db-sync-design.md` |
| 计划 1（基础设施） | `docs/superpowers/plans/2026-07-25-plan1-infrastructure.md` |
| SSO E2E 测试脚本 | `deploy/scripts/test-sso-e2e.sh` |
| DB 角色创建脚本 | `deploy/scripts/setup-db-roles.sh` |
| 数据迁移脚本 | `deploy/scripts/migrate-monitor-data.sh` |

**关键提醒**：
- `.env.prod` 文件含敏感凭据，已在 `.gitignore` 排除，禁止入仓
- 修改 nginx 配置后务必先 `nginx -t` 测试再 `reload`
- 数据库操作前先备份（`pg_dump`）
- `monitor_user` 密码变更后需同步更新 `.env.prod` 并重启 index-monitor
