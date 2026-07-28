#!/bin/bash
# =============================================================================
# dev.sh — GEO FLOW + LUMORA CITE 本地全量项目一键启动脚本
#
# 用法:
#   ./dev.sh start    启动全部服务（GEOFlow → index-monitor → Dashboard）
#   ./dev.sh stop     停止全部服务
#   ./dev.sh restart  重启全部服务
#   ./dev.sh status   查看所有服务状态和访问地址
#   ./dev.sh logs     查看所有服务最近日志
#   ./dev.sh init-db  初始化/迁移 monitor 数据库（首次部署或表缺失时使用）
#   ./dev.sh clean    停止服务并清理容器（保留数据卷）
#
# 服务架构:
#   GEOFlow       (Docker)  → localhost:18080  (admin 后台 + SSO + PostgreSQL)
#   index-monitor (Docker)  → localhost:8090   (监测系统 API)
#   Dashboard     (Vite)    → localhost:3000   (Vue 前端)
# =============================================================================

set -euo pipefail

# ── 路径与常量 ────────────────────────────────────────────────────────────────
# 脚本所在目录即项目根目录（路径含空格，所有变量引用必须加双引号）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEOFLOW_DIR="$PROJECT_ROOT/GEOFlow-main"
MONITOR_DIR="$PROJECT_ROOT/index-monitor"
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"
COMPOSE_LOCAL="$PROJECT_ROOT/docker-compose.local.yml"
VITE_PID_FILE="$PROJECT_ROOT/.dev-vite.pid"
VITE_LOG_FILE="$PROJECT_ROOT/.dev-vite.log"

# 服务端口
PORT_GEOFLOW=18080
PORT_MONITOR=8090
PORT_DASHBOARD=3000
PORT_PG=15432

# 测试账号
GEOFLOW_ADMIN_USER="admin"
GEOFLOW_ADMIN_PASS="admin123456"
MONITOR_CLIENT_USER="demo"
MONITOR_CLIENT_PASS="demo123456"

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_RESET="\033[0m"
  C_BOLD="\033[1m"
  C_RED="\033[31m"
  C_GREEN="\033[32m"
  C_YELLOW="\033[33m"
  C_BLUE="\033[34m"
  C_CYAN="\033[36m"
  C_GRAY="\033[90m"
else
  C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""; C_CYAN=""; C_GRAY=""
fi

info()    { echo -e "${C_CYAN}▸${C_RESET} $*"; }
success() { echo -e "${C_GREEN}✓${C_RESET} $*"; }
warn()    { echo -e "${C_YELLOW}⚠${C_RESET} $*"; }
error()   { echo -e "${C_RED}✗${C_RESET} $*" >&2; }
section() { echo -e "\n${C_BOLD}${C_BLUE}═══ $* ═══${C_RESET}"; }

# ── 工具函数 ──────────────────────────────────────────────────────────────────

# 检查 Docker 是否运行
check_docker() {
  if ! docker info >/dev/null 2>&1; then
    error "Docker 未运行，请先启动 Docker daemon"
    exit 1
  fi
}

# 等待容器健康（参数：容器名、超时秒数）
wait_container_healthy() {
  local container="$1"
  local timeout="${2:-60}"
  local elapsed=0
  while [[ $elapsed -lt $timeout ]]; do
    local status
    status="$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "none")"
    if [[ "$status" == "healthy" ]]; then
      return 0
    fi
    printf "\r${C_GRAY}  等待 %s 就绪... (%ds/%ds)${C_RESET}" "$container" "$elapsed" "$timeout"
    sleep 3
    elapsed=$((elapsed + 3))
  done
  echo ""
  error "$container 在 ${timeout}s 内未就绪"
  return 1
}

# 等待 HTTP 端点返回指定状态码（参数：URL、期望状态码、超时秒数）
wait_http() {
  local url="$1"
  local expected="${2:-200}"
  local timeout="${3:-30}"
  local elapsed=0
  while [[ $elapsed -lt $timeout ]]; do
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' "$url" --max-time 3 2>/dev/null || echo "000")"
    if [[ "$code" == "$expected" ]]; then
      return 0
    fi
    printf "\r${C_GRAY}  等待 %s 返回 %s... (%ds/%ds)${C_RESET}" "$url" "$expected" "$elapsed" "$timeout"
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo ""
  return 1
}

# 检查端口是否被占用（参数：端口号）
port_in_use() {
  local port="$1"
  ss -tlnp 2>/dev/null | grep -q ":${port} " || lsof -i :"$port" >/dev/null 2>&1
}

# ── 启动 GEOFlow ──────────────────────────────────────────────────────────────
start_geoflow() {
  section "启动 GEOFlow（内容分发引擎）"

  # 检查是否已在运行
  if docker ps --format '{{.Names}}' | grep -q '^geoflow-app$'; then
    success "GEOFlow 已在运行"
    return 0
  fi

  # 智能启动策略：
  #   - 如果 geoflow-app 镜像已构建 + 前端产物已存在 → 跳过 assets/init，直接启动运行时服务
  #     （避免每次启动都拉取 node 镜像重新构建前端，大幅加速启动）
  #   - 否则 → 完整 docker compose up（首次部署场景）
  local app_image_exists build_exists
  app_image_exists="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -c '^geoflow-app:latest$' || echo 0)"
  build_exists="no"
  [[ -f "$GEOFLOW_DIR/public/build/manifest.json" ]] && build_exists="yes"

  if [[ "$app_image_exists" -gt 0 && "$build_exists" == "yes" ]]; then
    info "检测到已构建镜像 + 前端产物，快速启动（跳过 assets 构建）..."
    # 确保 postgres 和 redis 先启动
    docker compose -f "$GEOFLOW_DIR/docker-compose.yml" up -d postgres redis 2>&1 | sed 's/^/  /'
    # 直接启动运行时服务，跳过 assets/init 依赖
    docker compose -f "$GEOFLOW_DIR/docker-compose.yml" up -d --no-deps app queue scheduler 2>&1 | sed 's/^/  /'
  else
    info "首次部署或缺少构建产物，完整启动（含前端构建）..."
    docker compose -f "$GEOFLOW_DIR/docker-compose.yml" up -d 2>&1 | sed 's/^/  /'
  fi

  # 等待 PostgreSQL 健康
  info "等待 GEOFlow PostgreSQL 就绪..."
  if ! wait_container_healthy geoflow-postgres 90; then
    error "GEOFlow PostgreSQL 启动失败"
    docker logs geoflow-postgres --tail 20 2>&1 | sed 's/^/  /'
    exit 1
  fi
  echo ""
  success "GEOFlow PostgreSQL 就绪"

  # 等待 GEOFlow 应用就绪
  info "等待 GEOFlow 应用就绪..."
  if ! wait_http "http://localhost:$PORT_GEOFLOW/" 200 60; then
    warn "GEOFlow 应用未在预期时间内就绪，可能仍在启动中"
  else
    success "GEOFlow 应用就绪 (http://localhost:$PORT_GEOFLOW)"
  fi
}

# ── 初始化 monitor 数据库 ─────────────────────────────────────────────────────
init_monitor_db() {
  section "检查/初始化 monitor 数据库"

  # 检查 monitor schema 是否存在
  local schema_exists
  schema_exists="$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -tAc \
    "SELECT 1 FROM information_schema.schemata WHERE schema_name='monitor'" 2>/dev/null || echo "0")"

  if [[ "$schema_exists" == "1" ]]; then
    # 检查 clients 表是否存在（判断是否需要完整初始化）
    local table_count
    table_count="$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -tAc \
      "SELECT count(*) FROM pg_tables WHERE schemaname='monitor'" 2>/dev/null || echo "0")"

    if [[ "$table_count" -ge 10 ]]; then
      success "monitor schema 已存在（$table_count 张表），跳过初始化"
      # 仍执行 alembic upgrade head 确保迁移最新
      info "执行 alembic upgrade head（确保迁移最新）..."
      docker exec geo-index-monitor-local alembic upgrade head 2>&1 | sed 's/^/  /' || true
      ensure_test_data
      return 0
    fi
  fi

  info "monitor schema 缺失或表不完整，执行初始化..."

  # 1. 执行 init-db.sh 创建基础表
  info "执行 init-db.sh 创建基础表..."
  docker cp "$PROJECT_ROOT/deploy/scripts/init-db.sh" geoflow-postgres:/tmp/init-db.sh
  docker exec -e POSTGRES_USER=geo_user -e POSTGRES_DB=geo_flow geoflow-postgres bash /tmp/init-db.sh 2>&1 | sed 's/^/  /'

  # 2. 删除 init-db.sh 创建的 manual_distributions（alembic 003 会重建，010 会补 content_title）
  docker exec geoflow-postgres psql -U geo_user -d geo_flow -c \
    "DROP TABLE IF EXISTS monitor.manual_distributions CASCADE;" 2>&1 | sed 's/^/  /'

  # 3. 执行 alembic 迁移
  info "执行 alembic upgrade head..."
  docker exec geo-index-monitor-local alembic upgrade head 2>&1 | sed 's/^/  /'

  # 4. 补充 007 迁移遗漏的 service_date 列
  info "检查并补充 service_date 列..."
  docker exec geoflow-postgres psql -U geo_user -d geo_flow -c \
    "ALTER TABLE monitor.clients ADD COLUMN IF NOT EXISTS service_start_date DATE;
     ALTER TABLE monitor.clients ADD COLUMN IF NOT EXISTS service_end_date DATE;" 2>&1 | sed 's/^/  /'

  success "monitor 数据库初始化完成"
  ensure_test_data
}

# ── 确保测试数据存在（测试客户 + admin 密码） ─────────────────────────────────
ensure_test_data() {
  # 检查测试客户是否存在
  local client_exists
  client_exists="$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -tAc \
    "SELECT count(*) FROM monitor.clients WHERE username='demo'" 2>/dev/null || echo "0")"

  if [[ "$client_exists" == "0" ]]; then
    info "创建测试客户 (demo / demo123456)..."
    docker exec geo-index-monitor-local python -c "
import asyncio
from app.core.database import async_session
from app.core.security import hash_password
from app.models.client import Client
from sqlalchemy import select

async def create():
    async with async_session() as db:
        existing = await db.execute(select(Client).where(Client.username == 'demo'))
        if existing.scalar_one_or_none():
            print('  测试客户已存在')
            return
        client = Client(
            client_id='DEMO001', username='demo',
            password_hash=hash_password('demo123456'),
            email='demo@zkeeeai.com', phone='13800138000',
            company_name='演示公司', status='active',
            contact_name='演示联系人', contact_email='demo@zkeeeai.com',
            contact_phone='13800138000',
        )
        db.add(client)
        await db.commit()
        print('  测试客户创建成功')

asyncio.run(create())
" 2>&1 | sed 's/^/  /'
  else
    success "测试客户已存在"
  fi

  # 确保 GEOFlow admin 用户存在且密码正确
  info "确保 GEOFlow admin 账号就绪..."
  # 注意：用单引号包裹 PHP 代码，避免 bash 解析 $a 为 shell 变量
  docker exec geoflow-app php artisan tinker --execute='use App\Models\Admin; $a = Admin::where("username","admin")->first(); if (!$a) { Admin::create(["username"=>"admin","password"=>bcrypt("admin123456"),"email"=>"admin@zkeeeai.com","display_name"=>"超级管理员","role"=>"super_admin","status"=>"active"]); echo "  admin 用户已创建"; } else { $a->password = bcrypt("admin123456"); $a->save(); echo "  admin 密码已确保正确"; }' 2>&1 | sed 's/^/  /'
}

# ── 启动 index-monitor ────────────────────────────────────────────────────────
start_monitor() {
  section "启动 index-monitor（监测系统 API）"

  # 检查 geoflow-laravel_default 网络是否存在（index-monitor 依赖它连接 geoflow-postgres）
  local net_exists
  net_exists="$(docker network inspect geoflow-laravel_default --format '{{.Name}}' 2>/dev/null || echo "")"
  if [[ -z "$net_exists" ]]; then
    error "geoflow-laravel_default 网络不存在，请先启动 GEOFlow"
    exit 1
  fi

  if docker ps --format '{{.Names}}' | grep -q '^geo-index-monitor-local$'; then
    success "index-monitor 已在运行"
  else
    info "启动 index-monitor + Redis..."
    docker compose -f "$COMPOSE_LOCAL" up -d 2>&1 | sed 's/^/  /'

    # 等待 index-monitor 健康检查
    info "等待 index-monitor 就绪..."
    if ! wait_http "http://localhost:$PORT_MONITOR/health" 200 45; then
      warn "index-monitor 未在预期时间内就绪"
      docker logs geo-index-monitor-local --tail 15 2>&1 | sed 's/^/  /'
    else
      success "index-monitor 就绪 (http://localhost:$PORT_MONITOR)"
    fi
  fi

  # 初始化/迁移数据库
  init_monitor_db
}

# ── 启动 Dashboard 前端 ───────────────────────────────────────────────────────
start_dashboard() {
  section "启动 Dashboard 前端（Vue + Vite）"

  # 检查是否已有 vite 进程在运行
  if [[ -f "$VITE_PID_FILE" ]] && kill -0 "$(cat "$VITE_PID_FILE")" 2>/dev/null; then
    success "Dashboard 前端已在运行 (PID: $(cat "$VITE_PID_FILE"))"
    return 0
  fi

  # 检查端口是否被占用
  if port_in_use $PORT_DASHBOARD; then
    warn "端口 $PORT_DASHBOARD 已被占用，假设 Dashboard 前端已在运行"
    return 0
  fi

  # 检查 node_modules
  if [[ ! -d "$DASHBOARD_DIR/node_modules" ]]; then
    info "安装前端依赖 (npm install)..."
    cd "$DASHBOARD_DIR"
    npm install 2>&1 | sed 's/^/  /'
    cd "$PROJECT_ROOT"
  fi

  info "启动 Vite 开发服务器..."
  cd "$DASHBOARD_DIR"
  # 用 setsid 创建新会话，进程脱离终端（nohup 在某些 shell 环境下仍会被 SIGHUP 杀掉）
  # setsid 的 PID = 新进程组的 PGID，stop 时用 kill -TERM -$PID 杀整个进程组
  setsid npm run dev > "$VITE_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$VITE_PID_FILE"
  cd "$PROJECT_ROOT"

  # 等待 vite 就绪
  info "等待 Vite 开发服务器就绪..."
  if ! wait_http "http://localhost:$PORT_DASHBOARD/" 200 30; then
    warn "Vite 未在预期时间内就绪，查看日志: $VITE_LOG_FILE"
  else
    success "Dashboard 前端就绪 (http://localhost:$PORT_DASHBOARD)"
  fi
}

# ── 打印服务概览 ──────────────────────────────────────────────────────────────
print_overview() {
  section "服务概览"
  echo -e "  ${C_BOLD}GEOFlow 后台${C_RESET}       http://localhost:$PORT_GEOFLOW/geo_admin/login"
  echo -e "  ${C_GRAY}管理员账号${C_RESET}         $GEOFLOW_ADMIN_USER / $GEOFLOW_ADMIN_PASS"
  echo ""
  echo -e "  ${C_BOLD}Dashboard 前端${C_RESET}     http://localhost:$PORT_DASHBOARD/"
  echo -e "  ${C_GRAY}测试客户账号${C_RESET}       $MONITOR_CLIENT_USER / $MONITOR_CLIENT_PASS"
  echo ""
  echo -e "  ${C_BOLD}index-monitor API${C_RESET}  http://localhost:$PORT_MONITOR/health"
  echo -e "  ${C_BOLD}PostgreSQL${C_RESET}         localhost:$PORT_PG (geo_user / geo_password / geo_flow)"
  echo ""
  echo -e "  ${C_GRAY}停止服务: ./dev.sh stop${C_RESET}"
  echo -e "  ${C_GRAY}查看状态: ./dev.sh status${C_RESET}"
  echo -e "  ${C_GRAY}查看日志: ./dev.sh logs${C_RESET}"
}

# ── 命令: start ───────────────────────────────────────────────────────────────
cmd_start() {
  section "启动全量项目"
  check_docker

  start_geoflow
  start_monitor
  start_dashboard
  print_overview

  section "全部服务已启动"
  success "本地测试环境就绪！"
}

# ── 命令: stop ────────────────────────────────────────────────────────────────
cmd_stop() {
  section "停止全部服务"

  # 1. 停止 Dashboard 前端（setsid 创建的进程组，用负 PID kill 整组）
  if [[ -f "$VITE_PID_FILE" ]] && kill -0 "$(cat "$VITE_PID_FILE")" 2>/dev/null; then
    local pid
    pid="$(cat "$VITE_PID_FILE")"
    info "停止 Dashboard 前端 (PGID: $pid)..."
    # kill 进程组（负 PID），确保 vite 子进程也被终止
    kill -TERM "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    sleep 1
    kill -KILL "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    rm -f "$VITE_PID_FILE"
    success "Dashboard 前端已停止"
  else
    info "Dashboard 前端未在运行"
    rm -f "$VITE_PID_FILE"
  fi

  # 2. 停止 index-monitor（用 stop 而非 down，保留容器和数据卷）
  if docker ps -a --format '{{.Names}}' | grep -qE '^geo-index-monitor-local$|^geo-redis-local$'; then
    info "停止 index-monitor..."
    docker compose -f "$COMPOSE_LOCAL" stop 2>&1 | sed 's/^/  /'
    success "index-monitor 已停止"
  else
    info "index-monitor 未在运行"
  fi

  # 3. 停止 GEOFlow（用 stop 而非 down，保留容器和数据卷）
  if docker ps -a --format '{{.Names}}' | grep -q '^geoflow-app$'; then
    info "停止 GEOFlow..."
    docker compose -f "$GEOFLOW_DIR/docker-compose.yml" stop 2>&1 | sed 's/^/  /'
    success "GEOFlow 已停止"
  else
    info "GEOFlow 未在运行"
  fi

  section "全部服务已停止"
}

# ── 命令: restart ─────────────────────────────────────────────────────────────
cmd_restart() {
  cmd_stop
  sleep 2
  cmd_start
}

# ── 命令: status ──────────────────────────────────────────────────────────────
cmd_status() {
  section "服务状态"

  # Docker 容器状态
  echo -e "  ${C_BOLD}Docker 容器:${C_RESET}"
  local containers=("geoflow-app" "geoflow-postgres" "geoflow-redis" "geoflow-queue" "geoflow-scheduler" "geo-index-monitor-local" "geo-redis-local")
  for c in "${containers[@]}"; do
    local status
    status="$(docker ps -a --filter "name=^${c}$" --format '{{.Status}}' 2>/dev/null || echo "未创建")"
    if [[ -z "$status" ]]; then
      echo -e "    ${C_RED}✗${C_RESET} $c — 未创建"
    elif [[ "$status" == Up* ]]; then
      echo -e "    ${C_GREEN}✓${C_RESET} $c — $status"
    else
      echo -e "    ${C_YELLOW}⚠${C_RESET} $c — $status"
    fi
  done

  # Vite 进程状态
  echo -e "\n  ${C_BOLD}Dashboard 前端:${C_RESET}"
  if [[ -f "$VITE_PID_FILE" ]] && kill -0 "$(cat "$VITE_PID_FILE")" 2>/dev/null; then
    echo -e "    ${C_GREEN}✓${C_RESET} vite 运行中 (PID: $(cat "$VITE_PID_FILE"))"
  elif port_in_use $PORT_DASHBOARD; then
    echo -e "    ${C_GREEN}✓${C_RESET} 端口 $PORT_DASHBOARD 有服务（非脚本启动）"
  else
    echo -e "    ${C_RED}✗${C_RESET} vite 未运行"
  fi

  # HTTP 端点检测
  echo -e "\n  ${C_BOLD}HTTP 端点:${C_RESET}"
  local endpoints=(
    "GEOFlow 首页|$PORT_GEOFLOW|/"
    "GEOFlow 后台|$PORT_GEOFLOW|/geo_admin/login"
    "monitor API|$PORT_MONITOR|/health"
    "Dashboard|$PORT_DASHBOARD|/"
  )
  for ep in "${endpoints[@]}"; do
    IFS='|' read -r name port path <<< "$ep"
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${port}${path}" --max-time 3 2>/dev/null || echo "000")"
    if [[ "$code" == "200" || "$code" == "302" ]]; then
      echo -e "    ${C_GREEN}✓${C_RESET} $name — HTTP $code"
    elif [[ "$code" == "000" ]]; then
      echo -e "    ${C_RED}✗${C_RESET} $name — 无法连接"
    else
      echo -e "    ${C_YELLOW}⚠${C_RESET} $name — HTTP $code"
    fi
  done

  # 数据库表统计
  echo -e "\n  ${C_BOLD}数据库:${C_RESET}"
  local monitor_tables
  monitor_tables="$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname='monitor'" 2>/dev/null || echo "0")"
  local public_tables
  public_tables="$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -tAc \
    "SELECT count(*) FROM pg_tables WHERE schemaname='public'" 2>/dev/null || echo "0")"
  echo -e "    monitor schema: ${monitor_tables} 张表"
  echo -e "    public schema:  ${public_tables} 张表（GEOFlow）"

  echo ""
  print_overview
}

# ── 命令: logs ────────────────────────────────────────────────────────────────
cmd_logs() {
  section "服务日志（最近 30 行）"

  local services=("geoflow-app" "geo-index-monitor-local" "geoflow-postgres")
  for svc in "${services[@]}"; do
    echo -e "\n${C_BOLD}── $svc ──${C_RESET}"
    docker logs "$svc" --tail 30 2>&1 | sed 's/^/  /'
  done

  # Vite 日志
  if [[ -f "$VITE_LOG_FILE" ]]; then
    echo -e "\n${C_BOLD}── Dashboard (vite) ──${C_RESET}"
    tail -30 "$VITE_LOG_FILE" | sed 's/^/  /'
  fi
}

# ── 命令: init-db ─────────────────────────────────────────────────────────────
cmd_init_db() {
  section "初始化 monitor 数据库"
  check_docker

  # 确保 index-monitor 容器在运行（alembic 在其中执行）
  if ! docker ps --format '{{.Names}}' | grep -q '^geo-index-monitor-local$'; then
    info "index-monitor 未运行，先启动 GEOFlow + index-monitor..."
    start_geoflow

    info "启动 index-monitor（不启动 Dashboard）..."
    docker compose -f "$COMPOSE_LOCAL" up -d 2>&1 | sed 's/^/  /'
    sleep 5
  fi

  # 强制重新初始化
  info "删除并重建 monitor schema..."
  docker exec geoflow-postgres psql -U geo_user -d geo_flow -c \
    "DROP SCHEMA IF EXISTS monitor CASCADE; CREATE SCHEMA monitor;" 2>&1 | sed 's/^/  /'

  # 执行 init-db.sh
  info "执行 init-db.sh..."
  docker cp "$PROJECT_ROOT/deploy/scripts/init-db.sh" geoflow-postgres:/tmp/init-db.sh
  docker exec -e POSTGRES_USER=geo_user -e POSTGRES_DB=geo_flow geoflow-postgres bash /tmp/init-db.sh 2>&1 | sed 's/^/  /'

  # 删除 manual_distributions（alembic 003 会重建）
  docker exec geoflow-postgres psql -U geo_user -d geo_flow -c \
    "DROP TABLE IF EXISTS monitor.manual_distributions CASCADE;" 2>&1 | sed 's/^/  /'

  # 执行 alembic 迁移
  info "执行 alembic upgrade head..."
  docker exec geo-index-monitor-local alembic upgrade head 2>&1 | sed 's/^/  /'

  # 补充 service_date 列
  docker exec geoflow-postgres psql -U geo_user -d geo_flow -c \
    "ALTER TABLE monitor.clients ADD COLUMN IF NOT EXISTS service_start_date DATE;
     ALTER TABLE monitor.clients ADD COLUMN IF NOT EXISTS service_end_date DATE;" 2>&1 | sed 's/^/  /'

  # 创建测试客户
  info "创建测试客户..."
  docker exec geo-index-monitor-local python -c "
import asyncio
from app.core.database import async_session
from app.core.security import hash_password
from app.models.client import Client
from sqlalchemy import select

async def create():
    async with async_session() as db:
        existing = await db.execute(select(Client).where(Client.username == 'demo'))
        if existing.scalar_one_or_none():
            print('  测试客户已存在，跳过')
            return
        client = Client(
            client_id='DEMO001', username='demo',
            password_hash=hash_password('demo123456'),
            email='demo@zkeeeai.com', phone='13800138000',
            company_name='演示公司', status='active',
            contact_name='演示联系人', contact_email='demo@zkeeeai.com',
            contact_phone='13800138000',
        )
        db.add(client)
        await db.commit()
        print('  测试客户创建成功: demo / demo123456')

asyncio.run(create())
" 2>&1 | sed 's/^/  /'

  # 重置 GEOFlow admin 密码
  info "重置 GEOFlow admin 密码..."
  docker exec geoflow-app php artisan tinker --execute="
use App\\Models\\Admin;
\$a = Admin::where('username','admin')->first();
if (\$a) { \$a->password = bcrypt('admin123456'); \$a->save(); echo '  admin 密码已重置\n'; }
" 2>&1 | sed 's/^/  /'

  success "数据库初始化完成"
}

# ── 命令: clean ───────────────────────────────────────────────────────────────
cmd_clean() {
  section "停止服务并清理容器（保留数据卷）"
  cmd_stop

  info "清理已停止的容器..."
  docker compose -f "$COMPOSE_LOCAL" rm -f 2>&1 | sed 's/^/  /' || true
  docker compose -f "$GEOFLOW_DIR/docker-compose.yml" rm -f 2>&1 | sed 's/^/  /' || true

  success "清理完成（数据卷已保留）"
}

# ── 主入口 ────────────────────────────────────────────────────────────────────
main() {
  local cmd="${1:-}"
  case "$cmd" in
    start)    cmd_start ;;
    stop)     cmd_stop ;;
    restart)  cmd_restart ;;
    status)   cmd_status ;;
    logs)     cmd_logs ;;
    init-db)  cmd_init_db ;;
    clean)    cmd_clean ;;
    *)
      echo -e "${C_BOLD}用法:${C_RESET} ./dev.sh <命令>"
      echo ""
      echo "命令:"
      echo "  start    启动全部服务（GEOFlow → index-monitor → Dashboard）"
      echo "  stop     停止全部服务"
      echo "  restart  重启全部服务"
      echo "  status   查看所有服务状态和访问地址"
      echo "  logs     查看所有服务最近日志"
      echo "  init-db  初始化/迁移 monitor 数据库（首次部署或表缺失时使用）"
      echo "  clean    停止服务并清理容器（保留数据卷）"
      echo ""
      echo "示例:"
      echo "  ./dev.sh start    # 一键启动全部"
      echo "  ./dev.sh status   # 查看状态"
      echo "  ./dev.sh stop     # 一键停止"
      exit 1
      ;;
  esac
}

main "$@"
