#!/usr/bin/env bash
# M4 任务 10 补丁：E2E 测试脚本（D05+D17+D24 修复）
#
# 修复说明：
# - D05：配置端点路径 /system/config → /config
# - D17：补充核心链路测试（步骤 11-15：创建客户→录入→检测→查询→审计→清理）
# - D24：CORS 预检路径同步修正为 /config
#
# 共 15 步：1-10 冒烟测试 + 11-15 核心链路测试（需 ADMIN_TOKEN）
set -euo pipefail

MONITOR_URL="${MONITOR_URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

echo "=== M4 E2E 冒烟测试 ==="

# 步骤 1：健康检查
echo "[1/10] 健康检查"
curl -sf "$MONITOR_URL/api/v1/health" | grep -q "healthy" || { echo "FAIL: 健康检查"; exit 1; }

# 步骤 2：SSO 登录页可达（接受 302/307/308 重定向）
echo "[2/10] SSO 登录页"
curl -sf -o /dev/null -w "%{http_code}" "$MONITOR_URL/sso/login" | grep -qE "30[278]" || { echo "FAIL: SSO 登录页"; exit 1; }

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

# 步骤 10：域名状态（生产环境检查，本地无法验证，预期失败）
echo "[10/10] 域名状态"
curl -sf -o /dev/null -w "%{http_code}" "https://monitor.zkeeeai.com" | grep -q "200" || { echo "FAIL: 域名"; exit 1; }

echo "=== E2E 冒烟测试全部通过 ==="

# === D17 修复：核心链路测试（步骤 11-15，需 ADMIN_TOKEN）===
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
