#!/bin/bash
# =============================================================================
# server-deploy-stage1234.sh — 阶段1-4 全量部署脚本（在云端服务器上执行）
# =============================================================================
#
# 用途：
#   在云端服务器 124.220.33.188 上一键部署 LUMORA CITE 监测系统阶段 1-4
#   的全部改动。涵盖：git pull → 重建镜像 → 迁移数据库 → 重启容器 → 验证。
#
# 阶段 1-4 改动概览：
#   - 阶段 1：AI 监测链路重构（引用检测链路打通，移除收录检测前置依赖）
#   - 阶段 2：客户透明度（发稿量披露 + 回答快照 + AI 可见度得分）
#   - 阶段 3：Playwright 网页端模拟引擎（元宝等无 API 平台引用检测）
#   - 阶段 4：网页端校准 + 置信度标注（API 检测结果可信度量化）
#
# 前置条件：
#   1. 服务器上 /opt/geo-monitoring 目录存在且为 git 仓库（已配置 GitHub remote）
#   2. GEOFlow 生产栈已启动（geoflow-postgres-prod 容器 + geoflow-prod-net 网络）
#   3. .env.prod 已配置（SECRET_KEY / SSO_JWT_SECRET / POSTGRES_PASSWORD 等）
#   4. monitor schema 已在 geoflow-postgres-prod 创建
#
# 用法（在服务器上执行）：
#   cd /opt/geo-monitoring
#   bash deploy/scripts/server-deploy-stage1234.sh
#
# 回滚：
#   git reset --hard <上一个稳定 commit>
#   docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build
#
# 退出码：
#   0 = 部署成功，所有验证通过
#   1 = 部署失败（详见错误信息）
# =============================================================================

set -euo pipefail

# ============================================================================
# 配置常量
# ============================================================================
PROJECT_DIR="/opt/geo-monitoring"                  # 服务器上项目根目录
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
ENV_FILE="$PROJECT_DIR/.env.prod"
CONTAINER_MONITOR="geo-index-monitor"               # 生产环境容器名（无 -local 后缀）
CONTAINER_DASHBOARD="geo-dashboard"
CONTAINER_NGINX="geo-nginx"

# 预期的新增 API 路由（阶段 1-4）
EXPECTED_ROUTES=(
  "/api/v1/admin/calibration/results"
  "/api/v1/admin/calibration/trigger"
  "/api/v1/client/confidence"
  "/api/v1/client/rankings"
  "/api/v1/client/visibility"
  "/api/v1/client/work-report"
)

# 预期的 alembic 版本（阶段 4 最终版本）
EXPECTED_ALEMBIC_VERSION="016_citation_calibrations"

# 颜色输出
if [[ -t 1 ]]; then
  C_RESET="\033[0m"; C_GREEN="\033[32m"; C_RED="\033[31m"
  C_YELLOW="\033[33m"; C_CYAN="\033[36m"; C_BOLD="\033[1m"
else
  C_RESET=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_CYAN=""; C_BOLD=""
fi

# ============================================================================
# 日志工具
# ============================================================================
banner() {
  echo ""
  echo -e "${C_CYAN}${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
  echo -e "${C_CYAN}${C_BOLD}  $1${C_RESET}"
  echo -e "${C_CYAN}${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
}
info()  { echo -e "${C_CYAN}▶${C_RESET} $1"; }
ok()    { echo -e "${C_GREEN}✓${C_RESET} $1"; }
err()   { echo -e "${C_RED}✗${C_RESET} $1" >&2; }
die()   { err "$1"; exit 1; }

# ============================================================================
# Step 0: 环境检查
# ============================================================================
banner "Step 0: 环境检查"

[[ -d "$PROJECT_DIR" ]] || die "项目目录不存在: $PROJECT_DIR"
[[ -f "$COMPOSE_FILE" ]] || die "docker-compose.prod.yml 不存在: $COMPOSE_FILE"
[[ -f "$ENV_FILE" ]] || die ".env.prod 不存在: $ENV_FILE"

# 检查 GEOFlow PG 容器
docker ps --filter "name=geoflow-postgres-prod" --filter "status=running" --format '{{.Names}}' | \
  grep -q "geoflow-postgres-prod" || die "geoflow-postgres-prod 容器未运行，请先启动 GEOFlow 生产栈"

ok "环境检查通过"

# ============================================================================
# Step 1: git pull 拉取最新代码
# ============================================================================
banner "Step 1: 拉取最新代码（git pull）"

cd "$PROJECT_DIR"
info "当前 commit: $(git rev-parse --short HEAD)"
info "执行 git pull origin master..."
git pull origin master 2>&1 | sed 's/^/  /'
info "更新后 commit: $(git rev-parse --short HEAD)"

# 确认关键新文件存在
for f in \
  index-monitor/app/services/calibration_service.py \
  index-monitor/app/models/citation_calibration.py \
  index-monitor/app/services/web_simulation/yuanbao.py \
  index-monitor/app/models/article_question_mapping.py; do
  [[ -f "$f" ]] || die "关键文件缺失: $f（git pull 可能失败）"
done
ok "代码拉取完成，阶段 1-4 关键文件已就位"

# ============================================================================
# Step 2: 重建 Docker 镜像
# ============================================================================
banner "Step 2: 重建 index-monitor + dashboard 镜像"

info "执行 docker compose build（可能需要 2-5 分钟）..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build index-monitor dashboard 2>&1 | tail -15
ok "镜像重建完成"

# ============================================================================
# Step 3: 重启容器
# ============================================================================
banner "Step 3: 重启容器"

info "执行 docker compose up -d..."
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d 2>&1 | sed 's/^/  /'

info "等待容器就绪（最多 60 秒）..."
waited=0
while [[ $waited -lt 60 ]]; do
  if curl -sf -o /dev/null --max-time 3 http://localhost:8090/api/v1/health 2>/dev/null; then
    break
  fi
  sleep 3
  waited=$((waited + 3))
  echo -n "."
done
echo ""

curl -sf http://localhost:8090/api/v1/health >/dev/null 2>&1 || die "index-monitor 健康检查失败"
ok "index-monitor 健康检查通过"

# ============================================================================
# Step 4: 数据库迁移（alembic upgrade head）
# ============================================================================
banner "Step 4: 数据库迁移"

info "当前 alembic 版本:"
docker exec "$CONTAINER_MONITOR" alembic current 2>&1 | sed 's/^/  /' || true

info "执行 alembic upgrade head..."
docker exec "$CONTAINER_MONITOR" alembic upgrade head 2>&1 | sed 's/^/  /'

info "迁移后 alembic 版本:"
CURRENT_VERSION=$(docker exec "$CONTAINER_MONITOR" alembic current 2>&1 | grep -oE '[0-9]+_[a-z_]+' | head -1)
echo -e "  ${C_CYAN}$CURRENT_VERSION${C_RESET}"

if [[ "$CURRENT_VERSION" != "$EXPECTED_ALEMBIC_VERSION" ]]; then
  die "alembic 版本不匹配: 期望 $EXPECTED_ALEMBIC_VERSION，实际 $CURRENT_VERSION"
fi
ok "数据库迁移完成，已到 $EXPECTED_ALEMBIC_VERSION"

# ============================================================================
# Step 5: 验证新增 API 路由
# ============================================================================
banner "Step 5: 验证阶段 1-4 新增 API 路由"

info "检查 OpenAPI 中是否注册了 ${#EXPECTED_ROUTES[@]} 条新路由..."
REGISTERED_ROUTES=$(docker exec "$CONTAINER_MONITOR" python3 -c "
import httpx
r = httpx.get('http://localhost:8090/openapi.json', timeout=10)
paths = list(r.json().get('paths', {}).keys())
for p in paths:
    print(p)
" 2>/dev/null)

MISSING=0
for route in "${EXPECTED_ROUTES[@]}"; do
  if echo "$REGISTERED_ROUTES" | grep -q "^${route}$"; then
    ok "$route"
  else
    err "缺失路由: $route"
    MISSING=$((MISSING + 1))
  fi
done

[[ $MISSING -eq 0 ]] || die "有 $MISSING 条路由未注册，部署可能不完整"
ok "全部 ${#EXPECTED_ROUTES[@]} 条新路由已注册"

# ============================================================================
# Step 6: 验证前端页面
# ============================================================================
banner "Step 6: 验证前端页面可达性"

# HTTP 检查
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null)
if [[ "$HTTP_CODE" == "200" ]] || [[ "$HTTP_CODE" == "301" ]] || [[ "$HTTP_CODE" == "302" ]]; then
  ok "前端 HTTP 可达（$HTTP_CODE）"
else
  err "前端 HTTP 不可达（$HTTP_CODE）"
fi

# HTTPS 检查
HTTPS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost/ 2>/dev/null)
if [[ "$HTTPS_CODE" == "200" ]] || [[ "$HTTPS_CODE" == "301" ]] || [[ "$HTTPS_CODE" == "302" ]]; then
  ok "前端 HTTPS 可达（$HTTPS_CODE）"
else
  err "前端 HTTPS 不可达（$HTTPS_CODE）"
fi

# ============================================================================
# Step 7: 容器状态汇总
# ============================================================================
banner "Step 7: 容器状态汇总"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null

# ============================================================================
# 完成
# ============================================================================
banner "部署完成 ✓"

echo -e "  ${C_GREEN}阶段 1-4 全部改动已部署到生产环境${C_RESET}"
echo ""
echo "  访问地址："
echo "    Dashboard:  https://zkeeeai.com/"
echo "    API:        https://zkeeeai.com/api/v1/"
echo ""
echo "  下一步建议："
echo "    1. 在系统设置中配置各 AI 平台 API Key（DeepSeek/豆包/千问等）"
echo "    2. 录入客户发稿 URL（手动录入或 GEOFlow 同步）"
echo "    3. 触发文章-关键词关联推断（DeepSeek 自动分析）"
echo "    4. 触发引用检测扫描"
echo "    5. 管理端触发校准采样（POST /admin/calibration/trigger）"
echo ""
