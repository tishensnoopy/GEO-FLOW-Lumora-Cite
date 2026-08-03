#!/bin/bash
#=============================================================================
# GEO FLOW + LUMORA CITE + GEOwebsite 本地全量测试环境一键检查脚本
#
# 用法：bash scripts/local-test-check.sh
#
# 检查项：
#   1. Docker 容器状态（8 个容器）
#   2. HTTP 服务可访问性（6 个服务）
#   3. 数据库连通性 + schema 隔离
#   4. SSO 重定向链
#   5. GEOwebsite webhook 健康检查
#   6. 推送对接配置
#   7. 数据互通基础（文章/分发/客户数据）
#=============================================================================

set -uo pipefail

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PASS=0
FAIL=0
WARN=0

# 项目路径
GEOFLOW_DIR="/home/tishensnoopy/GEO FLOW+LUMORA CITE/GEOFlow-main"
MONITOR_DIR="/home/tishensnoopy/GEO FLOW+LUMORA CITE/index-monitor"
DASHBOARD_DIR="/home/tishensnoopy/GEO FLOW+LUMORA CITE/dashboard"
GEOWEBSITE_DIR="/home/tishensnoopy/GEOwebsite"

# Webhook token（与 .env 中 GEOFLOW_OUTBOUND_SIGNING_KEY 一致）
WEBHOOK_TOKEN="38a2ab65af709848f0553bc668f58913"

print_header() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

check_pass() { echo -e "  ${GREEN}✅ $1${NC}"; PASS=$((PASS+1)); }
check_fail() { echo -e "  ${RED}❌ $1${NC}"; FAIL=$((FAIL+1)); }
check_warn() { echo -e "  ${YELLOW}⚠️  $1${NC}"; WARN=$((WARN+1)); }

# HTTP 状态码检查（静默，返回码）
http_code() {
    curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$1" 2>/dev/null || echo "000"
}

#=============================================================================
# 1. Docker 容器状态
#=============================================================================
print_header "1. Docker 容器状态检查"

EXPECTED_CONTAINERS=(
    "geoflow-postgres"
    "geoflow-redis"
    "geoflow-app"
    "geoflow-scheduler"
    "geoflow-queue"
    "geo-pg-local"
    "geo-redis-local"
    "geo-index-monitor-local"
)

for name in "${EXPECTED_CONTAINERS[@]}"; do
    status=$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo "not_found")
    if [ "$status" = "running" ]; then
        check_pass "$name: running"
    else
        check_fail "$name: $status（期望 running）"
    fi
done

#=============================================================================
# 2. HTTP 服务可访问性
#=============================================================================
print_header "2. HTTP 服务可访问性检查"

# GEOFlow 首页
code=$(http_code "http://localhost:18080/")
[ "$code" = "200" ] && check_pass "GEOFlow 首页 (18080): $code" || check_fail "GEOFlow 首页 (18080): $code"

# GEOFlow 后台登录
code=$(http_code "http://localhost:18080/geo_admin/login")
[ "$code" = "200" ] && check_pass "GEOFlow 后台登录 (18080): $code" || check_fail "GEOFlow 后台登录 (18080): $code"

# index-monitor health
resp=$(curl -s --max-time 10 http://localhost:8090/api/v1/health 2>/dev/null || echo "")
[ "$resp" = '{"status":"healthy"}' ] && check_pass "index-monitor health (8090): healthy" || check_fail "index-monitor health (8090): $resp"

# Dashboard 前端
code=$(http_code "http://localhost:3000/")
[ "$code" = "200" ] && check_pass "Dashboard 前端 (3000): $code" || check_fail "Dashboard 前端 (3000): $code"

# GEOwebsite
code=$(http_code "http://localhost:3001/")
[ "$code" = "200" ] || [ "$code" = "307" ] && check_pass "GEOwebsite (3001): $code" || check_fail "GEOwebsite (3001): $code"

#=============================================================================
# 3. 数据库连通性 + schema 隔离
#=============================================================================
print_header "3. 数据库连通性 + Schema 隔离检查"

# GEOFlow public schema 表数
pub_tables=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs)
[ "$pub_tables" -gt 50 ] && check_pass "GEOFlow public schema: $pub_tables 张表" || check_fail "GEOFlow public schema: $pub_tables 张表（期望 >50）"

# LumoraCite monitor schema 表数
mon_tables=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='monitor';" 2>/dev/null | xargs)
[ "$mon_tables" -ge 13 ] && check_pass "LumoraCite monitor schema: $mon_tables 张表" || check_fail "LumoraCite monitor schema: $mon_tables 张表（期望 ≥13）"

# GEOwebsite 独立数据库（表在 payload schema 下）
geo_tables=$(docker exec geo-pg-local psql -U geo_owner -d geowebsite -t -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='payload';" 2>/dev/null | xargs)
[ "$geo_tables" -gt 0 ] && check_pass "GEOwebsite 独立数据库 (geo-pg-local:5432): $geo_tables 张表 (payload schema)" || check_warn "GEOwebsite 数据库: $geo_tables 张表"

#=============================================================================
# 4. SSO 重定向链
#=============================================================================
print_header "4. SSO 登录跳转链检查"

# index-monitor /sso/login → 307 → GEOFlow /sso/authorize
sso_redirect=$(curl -s -o /dev/null -w "%{redirect_url}" --max-time 10 http://localhost:8090/sso/login 2>/dev/null || echo "")
if echo "$sso_redirect" | grep -q "localhost:18080/sso/authorize"; then
    check_pass "SSO 重定向: /sso/login → GEOFlow /sso/authorize"
else
    check_fail "SSO 重定向异常: $sso_redirect"
fi

# GEOFlow /sso/authorize 状态码
code=$(http_code "http://localhost:18080/sso/authorize?response_type=code&client_id=monitor&redirect_uri=http://localhost:8090/sso/callback&state=test")
[ "$code" = "302" ] || [ "$code" = "200" ] && check_pass "GEOFlow SSO authorize: $code" || check_warn "GEOFlow SSO authorize: $code"

#=============================================================================
# 5. GEOwebsite webhook 健康检查
#=============================================================================
print_header "5. GEOwebsite Webhook 推送接口检查"

# health.check
resp=$(curl -s --max-time 30 -X POST http://localhost:3001/api/geoflow-webhook \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $WEBHOOK_TOKEN" \
    -d '{"event":"health.check"}' 2>/dev/null || echo "")

if echo "$resp" | grep -q '"ok":true'; then
    check_pass "Webhook health.check: $resp"
else
    check_fail "Webhook health.check 失败: $resp"
fi

# 认证检查（无 token 应返回 401）
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 -X POST http://localhost:3001/api/geoflow-webhook \
    -H "Content-Type: application/json" \
    -d '{"event":"health.check"}' 2>/dev/null || echo "000")
[ "$code" = "401" ] && check_pass "Webhook 认证拦截（无 token 返回 401）" || check_warn "Webhook 认证未拦截: $code"

#=============================================================================
# 6. 推送对接配置
#=============================================================================
print_header "6. GEOFLOW→GEOwebsite 推送对接配置检查"

# GEOFLOW_OUTBOUND_PRIVATE_TARGETS
targets=$(grep "^GEOFLOW_OUTBOUND_PRIVATE_TARGETS=" "$GEOFLOW_DIR/.env" 2>/dev/null | cut -d= -f2)
if echo "$targets" | grep -q "geoflow-webhook"; then
    check_pass "GEOFLOW_OUTBOUND_PRIVATE_TARGETS: $targets"
else
    check_fail "GEOFLOW_OUTBOUND_PRIVATE_TARGETS 未配置或错误: $targets"
fi

# GEOFLOW_OUTBOUND_SIGNING_KEY
key=$(grep "^GEOFLOW_OUTBOUND_SIGNING_KEY=" "$GEOFLOW_DIR/.env" 2>/dev/null | cut -d= -f2)
[ -n "$key" ] && check_pass "GEOFLOW_OUTBOUND_SIGNING_KEY: 已配置 (${key:0:8}...)" || check_fail "GEOFLOW_OUTBOUND_SIGNING_KEY: 未配置"

# GEOwebsite GEOFLOW_WEBHOOK_TOKEN
token=$(grep "^GEOFLOW_WEBHOOK_TOKEN=" "$GEOWEBSITE_DIR/.env" 2>/dev/null | cut -d= -f2)
[ "$token" = "$WEBHOOK_TOKEN" ] && check_pass "GEOFLOW_WEBHOOK_TOKEN: 与 SIGNING_KEY 一致" || check_fail "GEOFLOW_WEBHOOK_TOKEN 不匹配"

#=============================================================================
# 7. 数据互通基础
#=============================================================================
print_header "7. 数据互通基础检查"

# GEOFlow 文章数
articles=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM public.articles;" 2>/dev/null | xargs)
[ "$articles" -gt 0 ] && check_pass "GEOFlow 文章: $articles 篇" || check_warn "GEOFlow 文章: $articles 篇（无数据，需在后台创建）"

# GEOFlow 分发记录
dists=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM public.article_distributions;" 2>/dev/null | xargs)
[ "$dists" -gt 0 ] && check_pass "GEOFlow 分发记录: $dists 条" || check_warn "GEOFlow 分发记录: $dists 条（无数据，需在后台分发文章）"

# monitor 客户数
clients=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM monitor.clients;" 2>/dev/null | xargs)
[ "$clients" -gt 0 ] && check_pass "LumoraCite 客户: $clients 个" || check_warn "LumoraCite 客户: $clients 个"

# monitor 手动分发
manual=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM monitor.manual_distributions;" 2>/dev/null | xargs)
[ "$manual" -gt 0 ] && check_pass "LumoraCite 手动分发: $manual 条" || check_warn "LumoraCite 手动分发: $manual 条"

# AI API Key 配置状态
ai_keys=$(docker exec geoflow-postgres psql -U geo_user -d geo_flow -t -c \
    "SELECT count(*) FROM monitor.system_config WHERE config_key LIKE 'ai_%_api_key' AND config_value != '' AND config_value IS NOT NULL;" 2>/dev/null | xargs)
[ "$ai_keys" -gt 0 ] && check_pass "AI API Key: $ai_keys 个已配置" || check_warn "AI API Key: $ai_keys 个已配置（需在 Dashboard 设置页配置）"

#=============================================================================
# 汇总
#=============================================================================
print_header "检查汇总"
echo -e "  ${GREEN}通过: $PASS${NC}  ${RED}失败: $FAIL${NC}  ${YELLOW}警告: $WARN${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}存在失败项，请按上述提示修复后重新运行。${NC}"
    exit 1
elif [ "$WARN" -gt 0 ]; then
    echo -e "${YELLOW}所有核心服务正常，但有 $WARN 个警告（数据/配置待完善）。${NC}"
    echo -e "${YELLOW}请按警告提示在对应后台补充数据或配置。${NC}"
    exit 0
else
    echo -e "${GREEN}全部检查通过！测试环境就绪。${NC}"
    exit 0
fi
