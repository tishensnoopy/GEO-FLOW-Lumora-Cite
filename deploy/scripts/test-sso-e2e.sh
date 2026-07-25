#!/bin/bash
# deploy/scripts/test-sso-e2e.sh
#
# SSO 端到端冒烟测试：GEOFlow SSO 端点 → 监测系统 SSO 端点全链路可达性。
#
# 默认目标为生产域名（zkeeeai.com / monitor.zkeeeai.com）。
# 本地运行时通过环境变量覆盖：
#   GEOFLOW_URL=http://localhost:8000 MONITOR_URL=http://localhost:8001 bash deploy/scripts/test-sso-e2e.sh
#
# 说明：
# - 生产 HTTPS 使用自签或非标准证书链时，curl 加 -k 兜底（insecure）。
# - 步骤 3 不使用 -L：监测系统 /sso/login 返回 RedirectResponse（307/302）到
#   GEOFlow /sso/authorize，跟随重定向会落到 GEOFlow 登录页 200，无法验证跳转本身。
# - 步骤 1 期望 302：GEOFlow /sso/authorize 未登录时跳 admin.login（见 routes/web.php:72）。
set -e

GEOFLOW_URL="${GEOFLOW_URL:-https://zkeeeai.com}"
MONITOR_URL="${MONITOR_URL:-https://monitor.zkeeeai.com}"

# HTTPS 兜底（自签/证书链问题）；本地 HTTP 时 -k 被忽略。
CURL_OPTS=(-s -k -o /dev/null -w "%{http_code}")

echo "=== SSO 端到端测试 ==="
echo "  GEOFLOW_URL=$GEOFLOW_URL"
echo "  MONITOR_URL=$MONITOR_URL"

# 1. 验证 GEOFlow SSO 授权端点存在（未登录 → 302 跳 admin.login）
echo "[1/5] 验证 GEOFlow SSO 授权端点..."
STATUS=$(curl "${CURL_OPTS[@]}" "$GEOFLOW_URL/sso/authorize?redirect_uri=$MONITOR_URL/sso/callback")
if [ "$STATUS" = "302" ] || [ "$STATUS" = "200" ]; then
    echo "  ✅ SSO 授权端点可访问（$STATUS）"
else
    echo "  ❌ SSO 授权端点返回 $STATUS（期望 302）"
    exit 1
fi

# 2. 验证 GEOFlow userinfo 端点拒绝无效 code（期望 400）
echo "[2/5] 验证 userinfo 端点拒绝无效 code..."
STATUS=$(curl "${CURL_OPTS[@]}" "$GEOFLOW_URL/api/sso/userinfo?code=invalid")
if [ "$STATUS" = "400" ]; then
    echo "  ✅ 无效 code 被拒绝"
else
    echo "  ❌ 无效 code 返回 $STATUS（期望 400）"
    exit 1
fi

# 3. 验证监测系统 SSO 登录端点（不跟随重定向，期望 307/302 跳 GEOFlow authorize）
echo "[3/5] 验证监测系统 SSO 登录端点..."
STATUS=$(curl "${CURL_OPTS[@]}" "$MONITOR_URL/sso/login")
if [ "$STATUS" = "307" ] || [ "$STATUS" = "302" ]; then
    echo "  ✅ SSO 登录端点返回重定向（$STATUS）"
else
    echo "  ❌ SSO 登录端点返回 $STATUS（期望 307 或 302）"
    exit 1
fi

# 4. 验证监测系统 callback 拒绝无效 code（期望 401）
#    CSRF 保护：先从 /sso/login 获取有效 state，再用无效 code 测试
echo "[4/5] 验证 callback 拒绝无效 code..."
LOGIN_REDIRECT=$(curl -s -k -o /dev/null -w "%{redirect_url}" "$MONITOR_URL/sso/login")
STATE=$(echo "$LOGIN_REDIRECT" | grep -oP 'state=\K[^&]+')
if [ -z "$STATE" ]; then
    echo "  ❌ 无法从 /sso/login 提取 state 参数"
    exit 1
fi
STATUS=$(curl "${CURL_OPTS[@]}" "$MONITOR_URL/sso/callback?code=invalid&state=$STATE")
if [ "$STATUS" = "401" ]; then
    echo "  ✅ 无效 code 被拒绝（401，使用有效 state）"
else
    echo "  ❌ 无效 code 返回 $STATUS（期望 401）"
    exit 1
fi

# 5. 验证监测系统 callback 拒绝缺少 code（期望 400）
#    使用新的有效 state（state 一次性消费，上次已用掉）
echo "[5/5] 验证 callback 拒绝缺少 code..."
LOGIN_REDIRECT2=$(curl -s -k -o /dev/null -w "%{redirect_url}" "$MONITOR_URL/sso/login")
STATE2=$(echo "$LOGIN_REDIRECT2" | grep -oP 'state=\K[^&]+')
STATUS=$(curl "${CURL_OPTS[@]}" "$MONITOR_URL/sso/callback?state=$STATE2")
if [ "$STATUS" = "400" ]; then
    echo "  ✅ 缺少 code 被拒绝（400，使用有效 state）"
else
    echo "  ❌ 缺少 code 返回 $STATUS（期望 400）"
    exit 1
fi

echo "=== SSO 端到端测试通过 ==="
