#!/bin/bash
# =============================================================================
# test-api.sh
# -----------------------------------------------------------------------------
# 用途：收录检测服务 API 端到端测试（本地集成测试 Task 8）
#       验证 6 个核心 API 端点 + DB 写入逻辑：
#         1. GET  /health                       健康检查
#         2. POST /api/v1/index/check            触发收录检测（无 body）
#         3. DB   index_results                  收录结果写入校验
#         4. DB   index_history                  历史记录写入校验
#         5. GET/PUT /api/v1/config             系统配置读写（末尾恢复）
#         6. POST /api/v1/scan/trigger/index     立即触发扫描
#
# 依赖：
#   - 3 容器已启动（geo-postgres-local / geo-redis-local / geo-index-monitor-local）
#   - seed-test-data.sh 已执行（art_001 / status='synced' 存在）
#   - jq 已安装（用于 JSON 解析；缺失时脚本自动 fallback 到 grep/sed）
#   - curl 已安装
#
# 幂等说明：
#   - 本脚本可重复执行
#   - POST /index/check 触发 check_all_pending，但 IndexChecker.get_pending_urls
#     仅返回 status='synced' 且未在 index_results 中的 URL。首次执行后 art_001
#     已写入 index_results，后续执行 check_all_pending 不会重复检测（设计行为，
#     非 bug）。DB 校验以「≥1 行匹配 URL」为标准，不要求「恰好 1 行」。
#   - /config PUT index_scan_frequency=2 后，末尾恢复原值，不污染配置。
#   - spider 真实访问 5 个搜索引擎（百度/头条/搜狗/360/必应），可能被 captcha/
#     限流；status 仅取 indexed / not_indexed 两值（spider 异常时返回 False →
#     not_indexed）。本脚本只验证 status 字段有合法值，不要求必须是 indexed。
#
# 用法：
#   bash deploy/scripts/test-api.sh
# =============================================================================
set -uo pipefail

# ---- 配置 --------------------------------------------------------------------
API_BASE="http://localhost:8090"
PSQL_CONTAINER="geo-postgres-local"
DB_USER="geo_user"
DB_NAME="geo_monitoring"
EXPECTED_URL="https://example.com/test-article-1"

# spider 最坏情况：5 引擎并发（semaphore=3）+ 每请求 30s timeout + 2-5s 随机延迟
# 实测约 40-90s，给 150s 余量
SPIDER_TIMEOUT=150

# ---- 工具函数 ----------------------------------------------------------------
FAILURES=0

# pass_fail <condition:0|1> <label> <detail>
pass_fail() {
    local cond="$1"
    local label="$2"
    local detail="${3:-}"
    if [ "$cond" = "1" ]; then
        echo "[PASS] $label"
    else
        echo "[FAIL] $label"
        FAILURES=$((FAILURES+1))
    fi
    if [ -n "$detail" ]; then
        echo "       $detail"
    fi
}

# json_get <json> <key> → 用 jq；jq 不可用时 grep/sed 兜底
json_get() {
    local json="$1"
    local key="$2"
    if command -v jq >/dev/null 2>&1; then
        echo "$json" | jq -r ".$key // empty" 2>/dev/null
    else
        echo "$json" | grep -oE "\"$key\"[[:space:]]*:[[:space:]]*\"?[^\"]*\"?" | head -1 \
            | sed -E 's/.*:[[:space:]]*"?([^"]*)"?$/\1/'
    fi
}

# psql_query <sql> → 输出 -t -A -F '|' 格式
psql_query() {
    docker exec -i "${PSQL_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" \
        -t -A -F '|' -v ON_ERROR_STOP=1 -c "$1" 2>&1
}

# =============================================================================
# 步骤 1：GET /health（健康检查）
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 1：GET /health（健康检查）"
echo "=========================================="
HEALTH_HTTP=$(curl -s -o /tmp/health_body -w "%{http_code}" --max-time 10 "${API_BASE}/health")
HEALTH_BODY=$(cat /tmp/health_body)
echo "HTTP: ${HEALTH_HTTP}"
echo "响应: ${HEALTH_BODY}"

HEALTH_STATUS=$(json_get "$HEALTH_BODY" "status")
pass_fail $([ "$HEALTH_HTTP" = "200" ] && echo 1 || echo 0) \
    "HTTP 状态码 = 200" \
    "实际: ${HEALTH_HTTP}"
pass_fail $([ "$HEALTH_STATUS" = "healthy" ] && echo 1 || echo 0) \
    "响应 status = healthy" \
    "实际: ${HEALTH_STATUS}"

# =============================================================================
# 步骤 2：POST /api/v1/index/check（触发收录检测，无 body）
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 2：POST /api/v1/index/check（触发收录检测，无 body）"
echo "=========================================="
echo "（spider 真实访问 5 个搜索引擎，最长等待 ${SPIDER_TIMEOUT}s）"
CHECK_HTTP=$(curl -s -o /tmp/check_body -w "%{http_code}" --max-time "${SPIDER_TIMEOUT}" \
    -X POST "${API_BASE}/api/v1/index/check")
CHECK_BODY=$(cat /tmp/check_body)
echo "HTTP: ${CHECK_HTTP}"
echo "响应: ${CHECK_BODY}"

CHECK_MSG=$(json_get "$CHECK_BODY" "message")
pass_fail $([ "$CHECK_HTTP" = "200" ] && echo 1 || echo 0) \
    "HTTP 状态码 = 200" \
    "实际: ${CHECK_HTTP}"
pass_fail $([ -n "$CHECK_MSG" ] && echo 1 || echo 0) \
    "响应包含 message 字段（实际实现返回 message 而非简报的 code/msg）" \
    "实际: ${CHECK_MSG}"

# =============================================================================
# 步骤 3：DB index_results 写入校验
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 3：DB index_results 写入校验"
echo "=========================================="
IR_ROWS=$(psql_query "SELECT url, baidu_status, toutiao_status, sogou_status, so360_status, bing_status FROM index_results WHERE url='${EXPECTED_URL}';")
echo "DB index_results 行（url|baidu|toutiao|sogou|so360|bing）:"
if [ -z "$IR_ROWS" ]; then
    echo "（无匹配行）"
else
    echo "${IR_ROWS}"
fi

IR_COUNT=$(echo "$IR_ROWS" | grep -c "^${EXPECTED_URL}|" || true)
pass_fail $([ "${IR_COUNT}" -ge 1 ] && echo 1 || echo 0) \
    "index_results 包含 ≥1 行匹配 ${EXPECTED_URL}" \
    "实际行数: ${IR_COUNT}"

# 校验 5 个 status 字段值合法（∈ {indexed, not_indexed}）
if [ "${IR_COUNT}" -ge 1 ]; then
    FIRST_ROW=$(echo "$IR_ROWS" | grep "^${EXPECTED_URL}|" | head -1)
    B_STATUS=$(echo "$FIRST_ROW" | cut -d'|' -f2)
    T_STATUS=$(echo "$FIRST_ROW" | cut -d'|' -f3)
    S_STATUS=$(echo "$FIRST_ROW" | cut -d'|' -f4)
    SO_STATUS=$(echo "$FIRST_ROW" | cut -d'|' -f5)
    BI_STATUS=$(echo "$FIRST_ROW" | cut -d'|' -f6)

    ALL_VALID=1
    for s in "$B_STATUS" "$T_STATUS" "$S_STATUS" "$SO_STATUS" "$BI_STATUS"; do
        if [ "$s" != "indexed" ] && [ "$s" != "not_indexed" ]; then
            ALL_VALID=0
        fi
    done
    pass_fail "$ALL_VALID" \
        "5 个搜索引擎 status 字段 ∈ {indexed, not_indexed}" \
        "baidu=${B_STATUS}, toutiao=${T_STATUS}, sogou=${S_STATUS}, so360=${SO_STATUS}, bing=${BI_STATUS}"
else
    pass_fail 0 \
        "5 个搜索引擎 status 字段 ∈ {indexed, not_indexed}" \
        "无匹配行，无法校验"
fi

# =============================================================================
# 步骤 4：DB index_history 写入校验
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 4：DB index_history 写入校验"
echo "=========================================="
IH_ROWS=$(psql_query "SELECT url, check_date, total_indexed FROM index_history WHERE url='${EXPECTED_URL}' ORDER BY check_date DESC;")
echo "DB index_history 行（url|check_date|total_indexed）:"
if [ -z "$IH_ROWS" ]; then
    echo "（无匹配行）"
else
    echo "${IH_ROWS}"
fi

IH_COUNT=$(echo "$IH_ROWS" | grep -c "^${EXPECTED_URL}|" || true)
pass_fail $([ "${IH_COUNT}" -ge 1 ] && echo 1 || echo 0) \
    "index_history 包含 ≥1 行匹配 ${EXPECTED_URL}" \
    "实际行数: ${IH_COUNT}"

if [ "${IH_COUNT}" -ge 1 ]; then
    FIRST_IH=$(echo "$IH_ROWS" | grep "^${EXPECTED_URL}|" | head -1)
    IH_DATE=$(echo "$FIRST_IH" | cut -d'|' -f2)
    IH_TOTAL=$(echo "$FIRST_IH" | cut -d'|' -f3)

    pass_fail $([ -n "$IH_DATE" ] && echo 1 || echo 0) \
        "check_date 非空" \
        "实际: ${IH_DATE}"

    # total_indexed 应为 0-5 之间数字
    TOTAL_VALID=0
    if [ "$IH_TOTAL" -ge 0 ] 2>/dev/null && [ "$IH_TOTAL" -le 5 ] 2>/dev/null; then
        TOTAL_VALID=1
    fi
    pass_fail "$TOTAL_VALID" \
        "total_indexed ∈ [0, 5]" \
        "实际: ${IH_TOTAL}"
else
    pass_fail 0 "check_date 非空" "无匹配行，无法校验"
    pass_fail 0 "total_indexed ∈ [0, 5]" "无匹配行，无法校验"
fi

# =============================================================================
# 步骤 5：GET/PUT /api/v1/config（系统配置读写 + 末尾恢复）
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 5：GET/PUT /api/v1/config（系统配置读写 + 恢复）"
echo "=========================================="

# 5a. GET 原始 config，捕获 index_scan_frequency 原值
CFG_GET_HTTP=$(curl -s -o /tmp/cfg_get -w "%{http_code}" --max-time 10 "${API_BASE}/api/v1/config")
CFG_GET_BODY=$(cat /tmp/cfg_get)
echo "GET /config HTTP: ${CFG_GET_HTTP}"
echo "GET /config 响应: ${CFG_GET_BODY}"

ORIG_FREQ=$(json_get "$CFG_GET_BODY" "index_scan_frequency")
echo "捕获原始 index_scan_frequency: ${ORIG_FREQ}"

pass_fail $([ "$CFG_GET_HTTP" = "200" ] && echo 1 || echo 0) \
    "GET /config HTTP = 200" \
    "实际: ${CFG_GET_HTTP}"

# 校验 GET 返回 8 个 key
CFG_KEY_COUNT=$(echo "$CFG_GET_BODY" | jq 'keys | length' 2>/dev/null || echo "0")
pass_fail $([ "$CFG_KEY_COUNT" = "8" ] && echo 1 || echo 0) \
    "GET /config 返回 8 个配置 key" \
    "实际: ${CFG_KEY_COUNT}"

# 5b. PUT 修改 index_scan_frequency 为 2
CFG_PUT_HTTP=$(curl -s -o /tmp/cfg_put -w "%{http_code}" --max-time 10 \
    -X PUT "${API_BASE}/api/v1/config" \
    -H "Content-Type: application/json" \
    -d '{"index_scan_frequency": "2"}')
CFG_PUT_BODY=$(cat /tmp/cfg_put)
echo "PUT /config HTTP: ${CFG_PUT_HTTP}"
echo "PUT /config 响应: ${CFG_PUT_BODY}"

pass_fail $([ "$CFG_PUT_HTTP" = "200" ] && echo 1 || echo 0) \
    "PUT /config HTTP = 200" \
    "实际: ${CFG_PUT_HTTP}"

# 5c. GET 确认更新生效
CFG_GET2_HTTP=$(curl -s -o /tmp/cfg_get2 -w "%{http_code}" --max-time 10 "${API_BASE}/api/v1/config")
CFG_GET2_BODY=$(cat /tmp/cfg_get2)
NEW_FREQ=$(json_get "$CFG_GET2_BODY" "index_scan_frequency")
echo "更新后 GET /config: ${CFG_GET2_BODY}"

pass_fail $([ "$NEW_FREQ" = "2" ] && echo 1 || echo 0) \
    "PUT 后 GET index_scan_frequency = 2" \
    "实际: ${NEW_FREQ}"

# 5d. 末尾恢复原值（不污染配置）
echo "恢复 index_scan_frequency -> ${ORIG_FREQ} ..."
CFG_RESTORE_HTTP=$(curl -s -o /tmp/cfg_restore -w "%{http_code}" --max-time 10 \
    -X PUT "${API_BASE}/api/v1/config" \
    -H "Content-Type: application/json" \
    -d "{\"index_scan_frequency\": \"${ORIG_FREQ}\"}")
RESTORE_BODY=$(cat /tmp/cfg_restore)
RESTORED_FREQ=$(json_get "$RESTORE_BODY" "index_scan_frequency")
pass_fail $([ "$RESTORED_FREQ" = "$ORIG_FREQ" ] && echo 1 || echo 0) \
    "末尾恢复 index_scan_frequency = ${ORIG_FREQ}" \
    "实际: ${RESTORED_FREQ}"

# =============================================================================
# 步骤 6：POST /api/v1/scan/trigger/index（立即触发扫描）
# =============================================================================
echo ""
echo "=========================================="
echo "步骤 6：POST /api/v1/scan/trigger/index（立即触发扫描）"
echo "=========================================="
echo "（同样调用 check_all_pending，最长等待 ${SPIDER_TIMEOUT}s）"
SCAN_HTTP=$(curl -s -o /tmp/scan_body -w "%{http_code}" --max-time "${SPIDER_TIMEOUT}" \
    -X POST "${API_BASE}/api/v1/scan/trigger/index")
SCAN_BODY=$(cat /tmp/scan_body)
echo "HTTP: ${SCAN_HTTP}"
echo "响应: ${SCAN_BODY}"

SCAN_MSG=$(json_get "$SCAN_BODY" "message")
pass_fail $([ "$SCAN_HTTP" = "200" ] && echo 1 || echo 0) \
    "HTTP 状态码 = 200" \
    "实际: ${SCAN_HTTP}"
pass_fail $([ -n "$SCAN_MSG" ] && echo 1 || echo 0) \
    "响应包含 message 字段" \
    "实际: ${SCAN_MSG}"

# =============================================================================
# 总结
# =============================================================================
echo ""
echo "=========================================="
echo "测试总结"
echo "=========================================="
if [ "${FAILURES}" -eq 0 ]; then
    echo "所有断言 [PASS]"
    exit 0
else
    echo "共 ${FAILURES} 项 [FAIL]，详见上方输出"
    exit 1
fi
