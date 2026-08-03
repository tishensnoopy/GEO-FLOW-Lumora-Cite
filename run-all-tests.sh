#!/bin/bash
# =============================================================================
# run-all-tests.sh — GEO FLOW + LUMORA CITE 全项目本地一键测试脚本
# =============================================================================
#
# 用途：
#   一键执行全项目（GEOFlow + LumoraCite/index-monitor + Dashboard）的本地测试，
#   覆盖单元测试、集成测试、契约测试与前端构建检查，并在结束时汇总通过/失败数。
#
# 项目架构与测试栈：
#   ┌──────────────────────────────────────────────────────────────────────┐
#   │ GEOFlow-main      (Laravel 12 / PHP 8.4)  → 容器 geoflow-app        │
#   │   测试框架: PHPUnit (phpunit.xml)                                    │
#   │   测试目录: tests/Unit, tests/Feature                                │
#   │   DB 策略: sqlite :memory:（不依赖 PostgreSQL，测试自包含）          │
#   │   执行方式: docker exec geoflow-app php artisan test                 │
#   ├──────────────────────────────────────────────────────────────────────┤
#   │ index-monitor     (FastAPI / Python)     → 容器 geo-index-monitor   │
#   │   测试框架: pytest                                                    │
#   │   测试目录: tests/unit, tests/integration, tests/contract            │
#   │   DB 策略:                                                            │
#   │     - unit:        不依赖 DB（纯逻辑）                               │
#   │     - integration: 依赖真实 PostgreSQL（monitor schema）             │
#   │     - contract:    依赖真实 PostgreSQL（GEOFlow public schema）      │
#   │   执行方式: docker exec geo-index-monitor-local pytest tests/...     │
#   ├──────────────────────────────────────────────────────────────────────┤
#   │ dashboard         (Vue 3 / Vite)        → 主机 Node.js              │
#   │   无单元测试框架，改用 `npm run build` 做构建可达性检查              │
#   │   执行方式: cd dashboard && npm run build                            │
#   └──────────────────────────────────────────────────────────────────────┘
#
# 依赖：
#   - Docker 守护进程已运行
#   - GEOFlow 本地栈已启动（geoflow-app / geoflow-postgres 等容器）
#     若未启动，脚本会尝试调用 ./dev.sh start 自动拉起
#   - index-monitor 本地栈已启动（geo-index-monitor-local 容器）
#   - 主机有 node/npm（用于 dashboard 构建检查）
#
# 用法：
#   ./run-all-tests.sh              # 默认：运行全部测试（geoflow + monitor + dashboard）
#   ./run-all-tests.sh all          # 同上
#   ./run-all-tests.sh geoflow      # 仅 GEOFlow（PHPUnit）
#   ./run-all-tests.sh monitor      # 仅 index-monitor（pytest 全部）
#   ./run-all-tests.sh unit         # 仅 index-monitor 单元测试（不依赖 DB，最快）
#   ./run-all-tests.sh integration  # 仅 index-monitor 集成测试（依赖 DB）
#   ./run-all-tests.sh contract     # 仅 index-monitor 契约测试（依赖 GEOFlow schema）
#   ./run-all-tests.sh dashboard    # 仅 Dashboard 构建检查
#   ./run-all-tests.sh quick        # 快速模式：geoflow Unit + monitor unit + dashboard
#   ./run-all-tests.sh --help       # 显示帮助
#
# 退出码：
#   0 = 所有选中测试全部通过
#   1 = 至少有一项测试失败（详见汇总区）
#   2 = 环境检查失败（Docker 未运行 / 容器无法启动）
#
# 幂等性：
#   脚本可重复执行，不产生副作用。GEOFlow 测试用 sqlite 内存库，
#   index-monitor 测试只读 / 临时写入，不破坏既有数据。
# =============================================================================

# -e: 任一命令失败立即退出（但被 || 捕获的失败不会触发）
# -u: 引用未定义变量报错
# -o pipefail: 管道中任一环节失败则整条管道失败
set -uo pipefail

# =============================================================================
# 路径与常量定义
# =============================================================================
# 脚本所在目录即项目根目录（路径含空格，所有变量引用必须加双引号）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GEOFLOW_DIR="$PROJECT_ROOT/GEOFlow-main"        # GEOFlow Laravel 项目目录
MONITOR_DIR="$PROJECT_ROOT/index-monitor"        # LumoraCite 监测系统目录
DASHBOARD_DIR="$PROJECT_ROOT/dashboard"          # Vue 前端目录
DEV_SCRIPT="$PROJECT_ROOT/dev.sh"                # 本地全栈启动脚本（复用其启动逻辑）

# Docker 容器名（与 docker-compose.local.yml / GEOFlow docker-compose.yml 对齐）
CONTAINER_GEOFLOW="geoflow-app"                  # GEOFlow Laravel 应用容器
CONTAINER_MONITOR="geo-index-monitor-local"      # index-monitor FastAPI 容器
CONTAINER_PG="geoflow-postgres"                  # 共享 PostgreSQL 容器

# 服务端口（用于健康检查）
PORT_GEOFLOW=18080                               # GEOFlow admin 后台
PORT_MONITOR=8090                                # index-monitor API
PORT_PG=15432                                    # PostgreSQL 暴露端口

# 测试结果统计（全局累加）
TOTAL_PASS=0                                     # 通过的测试套件数
TOTAL_FAIL=0                                     # 失败的测试套件数
FAILED_SUITES=()                                 # 失败套件名称列表（用于汇总）

# =============================================================================
# 颜色输出定义
# =============================================================================
# 仅在终端交互时启用颜色，避免重定向到文件时出现 ANSI 转义码
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
  C_RESET=""; C_BOLD=""; C_RED=""; C_GREEN=""; C_YELLOW=""
  C_BLUE=""; C_CYAN=""; C_GRAY=""
fi

# =============================================================================
# 日志工具函数
# =============================================================================
# banner: 打印大标题分隔线，标志一个测试阶段的开始
# 用法: banner "GEOFlow 单元/功能测试"
banner() {
  local msg="$1"
  echo ""
  echo -e "${C_CYAN}${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
  echo -e "${C_CYAN}${C_BOLD}  ${msg}${C_RESET}"
  echo -e "${C_CYAN}${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
}

# info: 普通信息行（蓝色 ▶ 前缀）
info() {
  echo -e "${C_BLUE}▶ ${C_RESET}$1"
}

# warn: 警告信息（黄色 ⚠ 前缀），不中断脚本
warn() {
  echo -e "${C_YELLOW}⚠ 警告: ${C_RESET}$1" >&2
}

# error: 错误信息（红色 ✗ 前缀），不中断脚本
error() {
  echo -e "${C_RED}✗ 错误: ${C_RESET}$1" >&2
}

# pass: 标记一个测试套件通过
pass() {
  echo -e "${C_GREEN}✓ [通过] ${C_RESET}$1"
  TOTAL_PASS=$((TOTAL_PASS + 1))
}

# fail: 标记一个测试套件失败，并记录到失败列表
fail() {
  echo -e "${C_RED}✗ [失败] ${C_RESET}$1"
  TOTAL_FAIL=$((TOTAL_FAIL + 1))
  FAILED_SUITES+=("$1")
}

# skip: 标记一个测试套件被跳过（不计入通过/失败）
skip() {
  echo -e "${C_YELLOW}○ [跳过] ${C_RESET}$1"
}

# run_step: 执行一个命令并捕获退出码，不因 set -e 中断
# 用法: run_step "描述" command... ; rc=$?
run_step() {
  local desc="$1"; shift
  echo -e "${C_GRAY}  执行: $* ${C_RESET}"
  "$@" 2>&1
  return $?
}

# =============================================================================
# 环境检查函数
# =============================================================================

# check_docker: 确认 Docker 守护进程可用
# 返回 0=可用，1=不可用
check_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    error "未找到 docker 命令，请先安装 Docker"
    return 1
  fi
  if ! docker info >/dev/null 2>&1; then
    error "Docker 守护进程未运行，请先启动 Docker"
    return 1
  fi
  return 0
}

# container_running <容器名>: 判断容器是否在运行
# 返回 0=运行中，1=未运行
container_running() {
  local name="$1"
  docker ps --filter "name=^${name}$" --filter "status=running" --format '{{.Names}}' | grep -q "^${name}$"
}

# ensure_services: 确保测试所需的容器在运行
# 如果容器未运行，尝试调用 ./dev.sh start 拉起服务
# 返回 0=服务就绪，1=无法就绪
ensure_services() {
  info "检查容器运行状态..."

  # 先检查最关键的两个容器
  local need_start=0
  if ! container_running "$CONTAINER_GEOFLOW"; then
    warn "$CONTAINER_GEOFLOW 未运行"
    need_start=1
  fi
  if ! container_running "$CONTAINER_MONITOR"; then
    warn "$CONTAINER_MONITOR 未运行"
    need_start=1
  fi

  if [[ $need_start -eq 0 ]]; then
    info "所有关键容器均在运行"
    return 0
  fi

  # 尝试通过 dev.sh start 拉起服务
  if [[ -x "$DEV_SCRIPT" ]]; then
    info "尝试通过 ./dev.sh start 拉起本地服务栈（可能需要 1-2 分钟）..."
    bash "$DEV_SCRIPT" start >/dev/null 2>&1 || true
  else
    warn "未找到 $DEV_SCRIPT，无法自动启动服务"
  fi

  # 等待容器就绪（最多 90 秒）
  info "等待容器就绪..."
  local waited=0
  while [[ $waited -lt 90 ]]; do
    if container_running "$CONTAINER_GEOFLOW" && container_running "$CONTAINER_MONITOR"; then
      break
    fi
    sleep 5
    waited=$((waited + 5))
    echo -n "."
  done
  [[ $waited -gt 0 ]] && echo ""

  # 最终确认
  if ! container_running "$CONTAINER_GEOFLOW"; then
    error "$CONTAINER_GEOFLOW 仍未运行，请手动执行: ./dev.sh start"
    return 1
  fi
  if ! container_running "$CONTAINER_MONITOR"; then
    error "$CONTAINER_MONITOR 仍未运行，请手动执行: ./dev.sh start"
    return 1
  fi

  info "服务栈已就绪"
  return 0
}

# wait_for_http <url> <超时秒>: 等待 HTTP 端点可达
wait_for_http() {
  local url="$1"
  local timeout="${2:-30}"
  local waited=0
  while [[ $waited -lt $timeout ]]; do
    if curl -sf -o /dev/null --max-time 3 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  return 1
}

# ensure_geoflow_base_data: 确保 GEOFlow 基础数据已初始化
# index-monitor 的部分单元测试连接真实 DB，假设 authors.id=1 等基础数据存在。
# 若 authors 表为空，会触发外键违例导致 11+ 个测试失败。
# 本函数执行 init_base_data.php（幂等：按 slug 检查存在性，已存在则跳过），
# 确保 categories / authors / ai_models 等基础数据就绪。
# 返回 0=数据就绪，1=初始化失败
ensure_geoflow_base_data() {
  info "检查 GEOFlow 基础数据..."

  # 检查 authors 表是否有数据——空则说明基础数据未初始化
  local author_count
  author_count=$(docker exec "$CONTAINER_PG" \
    psql -U "${POSTGRES_USER:-geo_user}" -d geo_flow -t -c "SELECT COUNT(*) FROM public.authors;" 2>/dev/null | tr -d '[:space:]')

  if [[ "$author_count" -gt 0 ]] 2>/dev/null; then
    info "GEOFlow 基础数据已就绪（authors: ${author_count} 条）"
    return 0
  fi

  # authors 表为空，执行 init_base_data.php 初始化
  info "authors 表为空，执行 init_base_data.php 初始化基础数据..."
  if docker exec "$CONTAINER_GEOFLOW" php /var/www/html/init_base_data.php 2>&1 | sed 's/^/  /'; then
    pass "GEOFlow 基础数据初始化完成"
  else
    warn "init_base_data.php 执行失败，部分依赖 DB 的测试可能失败"
  fi
}

# =============================================================================
# GEOFlow 测试函数
# =============================================================================

# run_geoflow_tests: 在 geoflow-app 容器内执行 PHPUnit 测试
# phpunit.xml 已配置 sqlite :memory: 数据库，测试自包含，不依赖 PostgreSQL
run_geoflow_tests() {
  banner "GEOFlow 测试（PHPUnit / Laravel）"
  info "执行容器: $CONTAINER_GEOFLOW"
  info "测试目录: tests/Unit, tests/Feature"
  info "数据库:   sqlite :memory:（phpunit.xml 强制覆盖，不污染真实 DB）"
  echo ""

  # 确认容器内 phpunit 可执行
  if ! docker exec "$CONTAINER_GEOFLOW" test -f vendor/bin/phpunit 2>/dev/null; then
    error "容器内未找到 vendor/bin/phpunit，可能未执行 composer install"
    fail "GEOFlow PHPUnit"
    return 1
  fi

  # 先清理配置缓存，避免 .env 缓存干扰测试环境
  info "清理 Laravel 配置缓存..."
  docker exec "$CONTAINER_GEOFLOW" php artisan config:clear 2>&1 | sed 's/^/  /' || true

  # 执行 php artisan test（内部调用 vendor/bin/phpunit，带彩色输出与测试摘要）
  info "执行 php artisan test..."
  echo ""
  if docker exec "$CONTAINER_GEOFLOW" php artisan test --color=always 2>&1; then
    echo ""
    pass "GEOFlow PHPUnit（Unit + Feature）"
  else
    echo ""
    fail "GEOFlow PHPUnit（Unit + Feature）"
  fi
}

# =============================================================================
# index-monitor 测试函数
# =============================================================================

# run_monitor_tests <子目录> <显示名>: 在 index-monitor 容器内执行指定测试目录
# 用法: run_monitor_tests tests/unit "index-monitor 单元测试"
run_monitor_tests() {
  local test_path="$1"
  local display_name="$2"

  banner "$display_name"
  info "执行容器: $CONTAINER_MONITOR"
  info "测试路径: $test_path"
  echo ""

  # 确认容器内 pytest 可用
  if ! docker exec "$CONTAINER_MONITOR" which pytest >/dev/null 2>&1; then
    error "容器内未找到 pytest"
    fail "$display_name"
    return 1
  fi

  # 执行 pytest，-v 显示详细用例，--tb=short 失败时显示精简 traceback
  # -p no:cacheprovider 禁用 .pytest_cache（避免容器 root 与主机用户权限冲突）
  info "执行 pytest -v --tb=short..."
  echo ""
  if docker exec -e PYTHONDONTWRITEBYTECODE=1 "$CONTAINER_MONITOR" \
      pytest "$test_path" -v --tb=short -p no:cacheprovider 2>&1; then
    echo ""
    pass "$display_name"
  else
    echo ""
    fail "$display_name"
  fi
}

# run_monitor_unit: 仅单元测试（最快，不依赖 DB 写入）
# 注意：单元测试中部分用例（test_sso_auth）验证配置派生逻辑，需 unset
#       SSO_GEOFLOW_USERINFO_URL——docker-compose.local.yml 显式注入了该变量，
#       会绕过 config.py 的 BASE_URL 派生逻辑，导致派生测试失败。
#       unset 后测试用默认派生值，符合"单元测试应在干净环境运行"的原则。
#       保留 DB 连接变量（POSTGRES_*、DATABASE_URL），因部分单元测试会读 DB。
run_monitor_unit() {
  banner "index-monitor 单元测试（不依赖 DB 写入）"
  info "执行容器: $CONTAINER_MONITOR"
  info "测试路径: tests/unit"
  info "环境处理: unset SSO_GEOFLOW_USERINFO_URL（消除容器环境变量对派生逻辑的覆盖）"
  echo ""

  # 确认容器内 pytest 可用
  if ! docker exec "$CONTAINER_MONITOR" which pytest >/dev/null 2>&1; then
    error "容器内未找到 pytest"
    fail "index-monitor 单元测试"
    return 1
  fi

  # 用 sh -c 包裹，先 unset 干扰变量再执行 pytest
  # -p no:cacheprovider 禁用 .pytest_cache（避免容器 root 与主机用户权限冲突）
  info "执行 pytest tests/unit -v --tb=short..."
  echo ""
  if docker exec -e PYTHONDONTWRITEBYTECODE=1 "$CONTAINER_MONITOR" \
      sh -c 'unset SSO_GEOFLOW_USERINFO_URL && cd /app && pytest tests/unit -v --tb=short -p no:cacheprovider' 2>&1; then
    echo ""
    pass "index-monitor 单元测试"
  else
    echo ""
    fail "index-monitor 单元测试"
    warn "部分单元测试依赖 DB 基础数据（authors/categories 等），若 GEOFlow 基础数据未 seed 可能失败"
  fi
}

# run_monitor_integration: 集成测试（依赖 monitor schema）
run_monitor_integration() {
  run_monitor_tests "tests/integration" "index-monitor 集成测试（依赖 monitor schema）"
}

# run_monitor_contract: 契约测试（依赖 GEOFlow public schema）
# 无 DB 连接时 conftest.py 会自动 skip，不阻塞流程
run_monitor_contract() {
  banner "index-monitor 契约测试（GEOFlow schema 防腐层）"
  info "执行容器: $CONTAINER_MONITOR"
  info "测试路径: tests/contract"
  info "说明:     契约测试验证 GEOFlow schema 结构与仓储查询逻辑"
  info "          无 DB 连接时自动跳过（不阻塞流程）"
  echo ""

  if ! docker exec "$CONTAINER_MONITOR" which pytest >/dev/null 2>&1; then
    error "容器内未找到 pytest"
    fail "index-monitor 契约测试"
    return 1
  fi

  info "执行 pytest tests/contract -v --tb=short..."
  echo ""
  if docker exec -e PYTHONDONTWRITEBYTECODE=1 "$CONTAINER_MONITOR" \
      pytest tests/contract -v --tb=short -p no:cacheprovider 2>&1; then
    echo ""
    pass "index-monitor 契约测试"
  else
    echo ""
    fail "index-monitor 契约测试"
  fi
}

# run_monitor_all: 执行 index-monitor 全部测试（unit + integration + contract）
run_monitor_all() {
  run_monitor_unit
  run_monitor_integration
  run_monitor_contract
}

# run_dashboard_unit: 执行 vitest 单元测试（组件+路由+store+API 契约）
# 覆盖 tests/unit + tests/components，验证前端逻辑不回归
run_dashboard_unit() {
  banner "Dashboard 前端单元测试（Vue 3 / Vitest）"
  info "目录: $DASHBOARD_DIR"
  info "命令: npm run test（vitest run，单次执行）"
  echo ""

  # 检查 node/npm 可用
  if ! command -v npm >/dev/null 2>&1; then
    error "主机未安装 npm，跳过 Dashboard 单元测试"
    skip "Dashboard 单元测试（无 npm）"
    return 0
  fi

  # 检查目录存在
  if [[ ! -d "$DASHBOARD_DIR" ]]; then
    error "Dashboard 目录不存在: $DASHBOARD_DIR"
    fail "Dashboard 单元测试"
    return 1
  fi

  # 检查 node_modules，缺失则提示
  if [[ ! -d "$DASHBOARD_DIR/node_modules" ]]; then
    warn "node_modules 缺失，先执行 npm install..."
    (cd "$DASHBOARD_DIR" && npm install 2>&1 | sed 's/^/  /') || true
  fi

  info "执行 npm run test..."
  echo ""
  if (cd "$DASHBOARD_DIR" && npm run test 2>&1); then
    echo ""
    pass "Dashboard 单元测试"
  else
    echo ""
    fail "Dashboard 单元测试"
  fi
}

# =============================================================================
# Dashboard 测试函数
# =============================================================================

# run_dashboard_build: 执行 npm run build 做前端构建可达性检查
# 配合 run_dashboard_unit（vitest）使用：先跑单元测试，再跑构建
run_dashboard_build() {
  banner "Dashboard 前端构建检查（Vue 3 / Vite）"
  info "目录: $DASHBOARD_DIR"
  info "命令: npm run build（生产构建，验证无语法/导入错误）"
  echo ""

  # 检查 node/npm 可用
  if ! command -v npm >/dev/null 2>&1; then
    error "主机未安装 npm，跳过 Dashboard 构建检查"
    skip "Dashboard 构建检查（无 npm）"
    return 0
  fi

  # 检查目录存在
  if [[ ! -d "$DASHBOARD_DIR" ]]; then
    error "Dashboard 目录不存在: $DASHBOARD_DIR"
    fail "Dashboard 构建检查"
    return 1
  fi

  # 检查 node_modules，缺失则提示
  if [[ ! -d "$DASHBOARD_DIR/node_modules" ]]; then
    warn "node_modules 缺失，先执行 npm install..."
    (cd "$DASHBOARD_DIR" && npm install 2>&1 | sed 's/^/  /') || true
  fi

  info "执行 npm run build..."
  echo ""
  if (cd "$DASHBOARD_DIR" && npm run build 2>&1); then
    echo ""
    pass "Dashboard 构建检查"
  else
    echo ""
    fail "Dashboard 构建检查"
  fi
}

# =============================================================================
# 汇总函数
# =============================================================================

# print_summary: 打印最终测试汇总，设置退出码
print_summary() {
  banner "测试汇总"
  echo -e "  通过套件: ${C_GREEN}${TOTAL_PASS}${C_RESET}"
  echo -e "  失败套件: ${C_RED}${TOTAL_FAIL}${C_RESET}"
  echo ""

  if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
    echo -e "${C_RED}失败明细:${C_RESET}"
    for s in "${FAILED_SUITES[@]}"; do
      echo -e "  ${C_RED}✗${C_RESET} $s"
    done
    echo ""
  fi

  # 最终结论
  if [[ $TOTAL_FAIL -eq 0 ]]; then
    echo -e "${C_GREEN}${C_BOLD}全部测试通过 ✓${C_RESET}"
    return 0
  else
    echo -e "${C_RED}${C_BOLD}有 ${TOTAL_FAIL} 项测试失败 ✗${C_RESET}"
    return 1
  fi
}

# =============================================================================
# 帮助信息
# =============================================================================

show_help() {
  cat <<'EOF'
GEO FLOW + LUMORA CITE 全项目一键测试脚本

用法:
  ./run-all-tests.sh [目标]

可用目标:
  all           运行全部测试（默认）：geoflow + monitor + dashboard
  geoflow       仅 GEOFlow（PHPUnit Unit + Feature）
  monitor       仅 index-monitor 全部 pytest（unit + integration + contract）
  unit          仅 index-monitor 单元测试（最快，不依赖 DB）
  integration   仅 index-monitor 集成测试（依赖 monitor schema）
  contract      仅 index-monitor 契约测试（依赖 GEOFlow schema）
  dashboard     仅 Dashboard 单元测试 + 构建检查（vitest + npm run build）
  quick         快速模式：geoflow + monitor unit + dashboard（跳过集成/契约）

选项:
  --help, -h    显示此帮助信息

示例:
  ./run-all-tests.sh                    # 全量测试
  ./run-all-tests.sh unit               # 只跑最快的单元测试
  ./run-all-tests.sh quick              # 快速验证（不依赖 DB 的部分）

退出码:
  0 = 全部通过
  1 = 有失败
  2 = 环境检查失败
EOF
}

# =============================================================================
# 主流程
# =============================================================================

main() {
  # 解析参数，默认 all
  local target="${1:-all}"
  case "$target" in
    -h|--help) show_help; exit 0 ;;
    all|geoflow|monitor|unit|integration|contract|dashboard|quick) ;;
    *)
      error "未知目标: $target（使用 --help 查看可用目标）"
      exit 2
      ;;
  esac

  # 打印脚本启动横幅
  echo -e "${C_BOLD}${C_CYAN}"
  echo "╔═══════════════════════════════════════════════════════════════╗"
  echo "║   GEO FLOW + LUMORA CITE  全项目本地一键测试                 ║"
  echo "╚═══════════════════════════════════════════════════════════════╝"
  echo -e "${C_RESET}"
  info "测试目标: $target"
  info "项目根目录: $PROJECT_ROOT"
  echo ""

  # ---------------------------------------------------------------------
  # 阶段 0：环境检查
  # ---------------------------------------------------------------------
  banner "阶段 0：环境检查"

  # 检查 Docker
  if ! check_docker; then
    exit 2
  fi
  pass "Docker 守护进程可用"

  # dashboard 目标不需要 Docker 容器，跳过服务检查
  if [[ "$target" != "dashboard" ]]; then
    if ! ensure_services; then
      exit 2
    fi
    pass "关键容器运行中（$CONTAINER_GEOFLOW / $CONTAINER_MONITOR）"

    # 确保 GEOFlow 基础数据已初始化（index-monitor 测试依赖 authors 等基础数据）
    # 仅对涉及 index-monitor 的目标执行（geoflow 本身用 sqlite 内存库不依赖此数据）
    case "$target" in
      all|monitor|unit|integration|contract|quick)
        ensure_geoflow_base_data
        ;;
    esac
  else
    skip "服务检查（dashboard 模式不需要容器）"
  fi

  # ---------------------------------------------------------------------
  # 阶段 1+：按目标执行测试
  # ---------------------------------------------------------------------
  case "$target" in
    all)
      # 全量模式：GEOFlow → monitor 全部 → dashboard 单元+构建
      run_geoflow_tests
      run_monitor_all
      run_dashboard_unit
      run_dashboard_build
      ;;
    geoflow)
      run_geoflow_tests
      ;;
    monitor)
      run_monitor_all
      ;;
    unit)
      run_monitor_unit
      ;;
    integration)
      run_monitor_integration
      ;;
    contract)
      run_monitor_contract
      ;;
    dashboard)
      run_dashboard_unit
      run_dashboard_build
      ;;
    quick)
      # 快速模式：GEOFlow（含 Unit+Feature，sqlite 快）+ monitor unit + dashboard 单元+构建
      # 跳过 monitor integration/contract（依赖 DB，较慢）
      run_geoflow_tests
      run_monitor_unit
      run_dashboard_unit
      run_dashboard_build
      ;;
  esac

  # ---------------------------------------------------------------------
  # 最终汇总
  # ---------------------------------------------------------------------
  print_summary
  exit $?
}

# 调用主流程，传入所有参数
main "$@"
