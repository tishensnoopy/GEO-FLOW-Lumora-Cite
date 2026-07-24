#!/bin/bash
# deploy/scripts/test-task6.sh
#
# Task 6 验证脚本（TDD）：数据迁移脚本 + docker-compose 废弃旧 PG 容器
#
# 用法：bash deploy/scripts/test-task6.sh
#
# 验证项：
#   1. migrate-monitor-data.sh 存在、可执行、语法正确、包含关键迁移步骤
#   2. docker-compose.local.yml：index-monitor 指向 geoflow-postgres，旧 postgres 已废弃
#   3. docker-compose.prod.yml：index-monitor 指向 geoflow-postgres-prod，旧 postgres 已废弃
#   4. docker compose config 两个文件均通过语法验证
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_ROOT"

PASS_COUNT=0
FAIL_COUNT=0

pass() { echo "PASS: $*"; PASS_COUNT=$((PASS_COUNT + 1)); }
fail() { echo "FAIL: $*" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); }
assert() { # assert <condition> <message>
  if eval "$1"; then pass "$2"; else fail "$2"; fi
}

# ===========================================================================
# 测试 1：migrate-monitor-data.sh 存在且可执行
# ===========================================================================
SCRIPT="deploy/scripts/migrate-monitor-data.sh"
assert "[ -f '$SCRIPT' ]" "迁移脚本 $SCRIPT 存在"
assert "[ -x '$SCRIPT' ]" "迁移脚本可执行"

# ===========================================================================
# 测试 2：迁移脚本语法正确
# ===========================================================================
if [ -f "$SCRIPT" ]; then
  if bash -n "$SCRIPT" 2>/dev/null; then
    pass "迁移脚本语法正确"
  else
    fail "迁移脚本语法错误"
  fi
else
  fail "迁移脚本不存在，无法做语法检查"
fi

# ===========================================================================
# 测试 3：迁移脚本包含关键迁移步骤
# ===========================================================================
if [ -f "$SCRIPT" ]; then
  assert "grep -q 'pg_dump' '$SCRIPT'"        "迁移脚本包含 pg_dump 备份步骤"
  assert "grep -q 'CREATE SCHEMA' '$SCRIPT'"  "迁移脚本包含 CREATE SCHEMA 步骤"
  assert "grep -q 'monitor' '$SCRIPT'"        "迁移脚本引用 monitor schema"
  assert "grep -q 'psql' '$SCRIPT'"           "迁移脚本包含 psql 恢复/验证步骤"
  assert "grep -qE 'docker exec' '$SCRIPT'"   "迁移脚本通过 docker exec 操作容器"
  # 容器名应使用实际名称（而非 brief 中的 monitor-postgres/geo-postgres 错误名称）
  assert "grep -q 'geoflow-postgres' '$SCRIPT'" "迁移脚本引用 geoflow-postgres 容器"
else
  fail "迁移脚本不存在，无法检查关键步骤"
fi

# ===========================================================================
# 测试 4：docker-compose.local.yml - index-monitor 指向 geoflow-postgres
# ===========================================================================
LOCAL_COMPOSE="docker-compose.local.yml"
assert "[ -f '$LOCAL_COMPOSE' ]" "$LOCAL_COMPOSE 存在"

if [ -f "$LOCAL_COMPOSE" ]; then
  # POSTGRES_HOST 应为 geoflow-postgres（不再是 postgres）
  assert "grep -E 'POSTGRES_HOST:\\s*geoflow-postgres' '$LOCAL_COMPOSE' | grep -v geoflow-postgres-prod > /dev/null" \
    "$LOCAL_COMPOSE: index-monitor POSTGRES_HOST=geoflow-postgres"
  # 应设置 DATABASE_URL 指向 geoflow-postgres
  assert "grep -E 'DATABASE_URL.*geoflow-postgres' '$LOCAL_COMPOSE' > /dev/null" \
    "$LOCAL_COMPOSE: index-monitor DATABASE_URL 指向 geoflow-postgres"
fi

# ===========================================================================
# 测试 5：docker-compose.local.yml - 旧 postgres 服务已废弃
# ===========================================================================
if [ -f "$LOCAL_COMPOSE" ]; then
  # 旧的 postgres 服务定义应被注释掉（行首为 # 后跟 postgres:）
  # 注意：不能匹配 geoflow-postgres 这种字符串中的 "postgres:"
  # 用更精确的模式：行首可选空白 + # + 可选空白 + postgres:
  assert "grep -E '^[[:space:]]*#[[:space:]]*postgres:' '$LOCAL_COMPOSE' > /dev/null" \
    "$LOCAL_COMPOSE: 旧 postgres 服务已注释"
  # 应有 DEPRECATED/废弃 注释说明
  assert "grep -Ei 'DEPRECATED|废弃|deprecated' '$LOCAL_COMPOSE' > /dev/null" \
    "$LOCAL_COMPOSE: 含废弃说明注释"
  # index-monitor 不应再 depends_on postgres（注释掉的 depends_on 不算）
  # 提取 index-monitor 段落，检查未注释的 depends_on 是否包含 postgres
  if python3 -c "
import sys, yaml
with open('$LOCAL_COMPOSE') as f:
    cfg = yaml.safe_load(f)
im = cfg.get('services', {}).get('index-monitor', {})
deps = im.get('depends_on', {})
if isinstance(deps, dict):
    sys.exit(0 if 'postgres' not in deps else 1)
elif isinstance(deps, list):
    sys.exit(0 if 'postgres' not in deps else 1)
else:
    sys.exit(0)
" 2>/dev/null; then
    pass "$LOCAL_COMPOSE: index-monitor 不再 depends_on postgres"
  else
    fail "$LOCAL_COMPOSE: index-monitor 仍 depends_on postgres"
  fi
fi

# ===========================================================================
# 测试 6：docker-compose.prod.yml - index-monitor 指向 geoflow-postgres-prod
# ===========================================================================
PROD_COMPOSE="docker-compose.prod.yml"
assert "[ -f '$PROD_COMPOSE' ]" "$PROD_COMPOSE 存在"

if [ -f "$PROD_COMPOSE" ]; then
  assert "grep -E 'POSTGRES_HOST:\\s*geoflow-postgres-prod' '$PROD_COMPOSE' > /dev/null" \
    "$PROD_COMPOSE: index-monitor POSTGRES_HOST=geoflow-postgres-prod"
  assert "grep -E 'DATABASE_URL.*geoflow-postgres-prod' '$PROD_COMPOSE' > /dev/null" \
    "$PROD_COMPOSE: index-monitor DATABASE_URL 指向 geoflow-postgres-prod"
fi

# ===========================================================================
# 测试 7：docker-compose.prod.yml - 旧 postgres 服务已废弃
# ===========================================================================
if [ -f "$PROD_COMPOSE" ]; then
  assert "grep -E '^[[:space:]]*#[[:space:]]*postgres:' '$PROD_COMPOSE' > /dev/null" \
    "$PROD_COMPOSE: 旧 postgres 服务已注释"
  assert "grep -Ei 'DEPRECATED|废弃|deprecated' '$PROD_COMPOSE' > /dev/null" \
    "$PROD_COMPOSE: 含废弃说明注释"
  if python3 -c "
import sys, yaml
with open('$PROD_COMPOSE') as f:
    cfg = yaml.safe_load(f)
im = cfg.get('services', {}).get('index-monitor', {})
deps = im.get('depends_on', {})
if isinstance(deps, dict):
    sys.exit(0 if 'postgres' not in deps else 1)
elif isinstance(deps, list):
    sys.exit(0 if 'postgres' not in deps else 1)
else:
    sys.exit(0)
" 2>/dev/null; then
    pass "$PROD_COMPOSE: index-monitor 不再 depends_on postgres"
  else
    fail "$PROD_COMPOSE: index-monitor 仍 depends_on postgres"
  fi
fi

# ===========================================================================
# 测试 8：docker-compose.local.yml 配置语法有效
# ===========================================================================
if [ -f "$LOCAL_COMPOSE" ]; then
  if docker compose -f "$LOCAL_COMPOSE" config > /dev/null 2>&1; then
    pass "$LOCAL_COMPOSE: docker compose config 通过"
  else
    fail "$LOCAL_COMPOSE: docker compose config 失败"
    # 显示错误便于调试
    docker compose -f "$LOCAL_COMPOSE" config 2>&1 | head -20 >&2 || true
  fi
fi

# ===========================================================================
# 测试 9：docker-compose.prod.yml 配置语法有效（需 env vars）
# ===========================================================================
if [ -f "$PROD_COMPOSE" ]; then
  if POSTGRES_DB=geo_flow POSTGRES_USER=geo_user POSTGRES_PASSWORD=test-pw \
     REDIS_PASSWORD=test-pw SECRET_KEY=test-sk \
     docker compose -f "$PROD_COMPOSE" config > /dev/null 2>&1; then
    pass "$PROD_COMPOSE: docker compose config 通过（含 env vars）"
  else
    fail "$PROD_COMPOSE: docker compose config 失败"
    POSTGRES_DB=geo_flow POSTGRES_USER=geo_user POSTGRES_PASSWORD=test-pw \
      REDIS_PASSWORD=test-pw SECRET_KEY=test-sk \
      docker compose -f "$PROD_COMPOSE" config 2>&1 | head -20 >&2 || true
  fi
fi

# ===========================================================================
# 汇总
# ===========================================================================
echo ""
echo "=========================================="
echo " 通过: $PASS_COUNT   失败: $FAIL_COUNT"
echo "=========================================="
if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
exit 0
