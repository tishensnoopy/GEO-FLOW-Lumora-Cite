#!/bin/bash
# deploy/scripts/migrate-monitor-data.sh
#
# 将监测系统旧 PG 的数据迁移到 GEOFlow 的 PG（monitor schema）。
#
# Task 6：废弃监测系统独立 PG 容器，统一使用 GEOFlow 的 PG。
#   - 旧 PG 容器：geo-postgres-local（本地）/ geo-postgres（生产）
#   - 新 PG 容器：geoflow-postgres（本地）/ geoflow-postgres-prod（生产）
#   - 数据库：geo_flow（GEOFlow 的库；监测系统表存放在 monitor schema）
#
# 用法：
#   bash deploy/scripts/migrate-monitor-data.sh                  # 本地默认
#   DEPLOY_ENV=prod bash deploy/scripts/migrate-monitor-data.sh  # 生产
#
# 可通过环境变量覆盖默认值（一般无需覆盖）：
#   OLD_PG_CONTAINER, NEW_PG_CONTAINER,
#   OLD_DB_USER, OLD_DB_NAME, NEW_DB_USER, NEW_DB_NAME
#
# 退出码：
#   0 - 全部步骤成功
#   1 - 严重错误（set -e 触发）
#
# 注意：本脚本不会删除旧 PG 的数据；迁移后可手动确认再清理旧容器/卷。
set -euo pipefail

# --------------------------------------------------------------------------
# 配置（环境变量优先）
# --------------------------------------------------------------------------
DEPLOY_ENV="${DEPLOY_ENV:-local}"

if [ "$DEPLOY_ENV" = "prod" ]; then
    OLD_PG_CONTAINER="${OLD_PG_CONTAINER:-geo-postgres}"
    NEW_PG_CONTAINER="${NEW_PG_CONTAINER:-geoflow-postgres-prod}"
else
    OLD_PG_CONTAINER="${OLD_PG_CONTAINER:-geo-postgres-local}"
    NEW_PG_CONTAINER="${NEW_PG_CONTAINER:-geoflow-postgres}"
fi

OLD_DB_USER="${OLD_DB_USER:-geo_user}"
OLD_DB_NAME="${OLD_DB_NAME:-geo_monitoring}"
NEW_DB_USER="${NEW_DB_USER:-geo_user}"
NEW_DB_NAME="${NEW_DB_NAME:-geo_flow}"

BACKUP_FILE="/tmp/monitor_backup_${DEPLOY_ENV}_$$.sql"

# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
log() { echo "[migrate] $*"; }

cleanup() {
    if [ -n "${BACKUP_FILE:-}" ] && [ -f "${BACKUP_FILE:-}" ]; then
        log "清理临时备份文件 $BACKUP_FILE"
        rm -f "$BACKUP_FILE"
    fi
}
trap cleanup EXIT

# --------------------------------------------------------------------------
# 前置检查
# --------------------------------------------------------------------------
log "=== 监测系统数据迁移脚本（DEPLOY_ENV=$DEPLOY_ENV） ==="
log "旧 PG 容器: $OLD_PG_CONTAINER (db=$OLD_DB_NAME, user=$OLD_DB_USER)"
log "新 PG 容器: $NEW_PG_CONTAINER (db=$NEW_DB_NAME, user=$NEW_DB_USER)"
log ""

# 检查新 PG 容器是否在运行
if ! docker inspect "$NEW_PG_CONTAINER" > /dev/null 2>&1; then
    log "错误：新 PG 容器 $NEW_PG_CONTAINER 未运行。请先启动 GEOFlow 的 PG。"
    exit 1
fi

# --------------------------------------------------------------------------
# 步骤 1：备份旧 PG 数据
# --------------------------------------------------------------------------
log "[1/4] 备份旧 PG 数据..."

OLD_PG_AVAILABLE=0
if docker inspect "$OLD_PG_CONTAINER" > /dev/null 2>&1; then
    OLD_PG_AVAILABLE=1
fi

if [ "$OLD_PG_AVAILABLE" -eq 0 ]; then
    log "  旧 PG 容器 $OLD_PG_CONTAINER 不存在或未运行，跳过备份"
    BACKUP_FILE=""
elif docker exec "$OLD_PG_CONTAINER" psql -U "$OLD_DB_USER" -d "$OLD_DB_NAME" \
     -c "SELECT 1 FROM information_schema.schemata WHERE schema_name='monitor'" 2>/dev/null \
     | grep -q "1"; then
    # 旧 PG 已有 monitor schema（Task 1-5 之后的状态），直接导出 monitor schema
    log "  旧 PG 已有 monitor schema，导出 monitor schema"
    docker exec "$OLD_PG_CONTAINER" pg_dump -U "$OLD_DB_USER" -d "$OLD_DB_NAME" \
        --schema=monitor --no-owner --no-acl > "$BACKUP_FILE"
else
    # 旧 PG 表在 public schema（迁移前的老状态）
    log "  旧 PG 表在 public schema，导出后改写 schema 引用为 monitor"
    docker exec "$OLD_PG_CONTAINER" pg_dump -U "$OLD_DB_USER" -d "$OLD_DB_NAME" \
        --schema=public --no-owner --no-acl > "$BACKUP_FILE" 2>/dev/null || {
        log "  pg_dump 失败或无数据，跳过"
        BACKUP_FILE=""
    }
    if [ -n "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
        # 改写 dump 中的 schema 引用：SCHEMA public → SCHEMA monitor
        # 注意用 sed -i 就地修改；不同平台 sed 行为略有差异，使用临时文件兼容
        sed 's/SCHEMA public/SCHEMA monitor/g' "$BACKUP_FILE" > "${BACKUP_FILE}.tmp" \
            && mv "${BACKUP_FILE}.tmp" "$BACKUP_FILE"
    fi
fi

if [ -n "$BACKUP_FILE" ] && [ -s "$BACKUP_FILE" ]; then
    log "  备份完成：$(wc -l < "$BACKUP_FILE") 行 SQL"
else
    log "  无数据需要迁移"
    BACKUP_FILE=""
fi

# --------------------------------------------------------------------------
# 步骤 2：在新 PG 创建 monitor schema（幂等）
# --------------------------------------------------------------------------
log "[2/4] 在新 PG 创建 monitor schema..."
docker exec "$NEW_PG_CONTAINER" psql -U "$NEW_DB_USER" -d "$NEW_DB_NAME" \
    -c "CREATE SCHEMA IF NOT EXISTS monitor;"

# --------------------------------------------------------------------------
# 步骤 3：恢复数据到 monitor schema
# --------------------------------------------------------------------------
if [ -n "$BACKUP_FILE" ]; then
    log "[3/4] 恢复数据到 monitor schema..."
    # 遇到已存在对象时跳过（--no-owner + ON_ERROR_STOP 不开，避免冲突中断）
    docker exec -i "$NEW_PG_CONTAINER" psql -U "$NEW_DB_USER" -d "$NEW_DB_NAME" \
        -v ON_ERROR_STOP=0 < "$BACKUP_FILE" 2>&1 | grep -v "^NOTICE:" || true
else
    log "[3/4] 无需恢复（旧 PG 无数据）"
fi

# --------------------------------------------------------------------------
# 步骤 4：验证 monitor schema 表
# --------------------------------------------------------------------------
log "[4/4] 验证 monitor schema 表..."
docker exec "$NEW_PG_CONTAINER" psql -U "$NEW_DB_USER" -d "$NEW_DB_NAME" \
    -c "\dt monitor.*"

log ""
log "=== 迁移完成 ==="
log "提示："
log "  1. 如需让监测系统应用 alembic 版本与新 PG 对齐，请在 index-monitor 容器内执行："
log "     cd /app && alembic upgrade head"
log "  2. 确认数据无误后，可停止并删除旧 PG 容器与卷："
log "     docker rm -f $OLD_PG_CONTAINER"
log "  3. 本脚本不会删除旧 PG 数据，回滚方法："
log "     - 重启旧 PG 容器"
log "     - 把 docker-compose 配置改回指向旧 postgres 服务"
