#!/bin/bash
# deploy/scripts/setup-db-roles.sh
#
# 跨 schema DB 层权限隔离——创建 monitor_user 角色 + 授权（改进 2）。
#
# 目标（规格要求 #42）：
#   监测系统 DB 用户对 public schema 只读（SELECT），对 monitor schema 读写。
#
# 权限矩阵：
#   | Schema  | USAGE | CREATE | 表权限         | 序列权限 |
#   |---------|-------|--------|----------------|----------|
#   | public  | ✅    | ❌     | SELECT（只读） | —        |
#   | monitor | ✅    | ❌     | ALL（读写）    | ALL      |
#
# - 无 CREATE：DDL 留给 geo_user（alembic / Laravel migration 以 geo_user 运行）。
# - ALTER DEFAULT PRIVILEGES FOR ROLE geo_user：geo_user 未来新建表自动继承权限
#   （public 新表 → 自动 GRANT SELECT；monitor 新表 → 自动 GRANT ALL）。
#
# 幂等：可重复执行。角色已存在则跳过创建 + 更新密码；GRANT 天然幂等。
#
# 执行者权限约束：
#   `ALTER DEFAULT PRIVILEGES FOR ROLE geo_user` 要求执行者是 geo_user 本身、
#   geo_user 的成员角色、或超级用户。脚本默认 PGUSER=geo_user（既是 DB owner 又是
#   超级用户），满足此约束。若用其他管理账号执行，须为 geo_user 成员或超级用户。
#
# 用法：
#   MONITOR_DB_PASSWORD=xxx bash deploy/scripts/setup-db-roles.sh
#
# 可选环境变量（默认与 docker-compose 一致）：
#   PGHOST / PGPORT / PGUSER / PGDATABASE / PGPASSWORD  —— PG 连接参数
#   MONITOR_DB_PASSWORD  —— monitor_user 密码（必填，不硬编码）
#   MONITOR_DB_USER      —— 角色名（默认 monitor_user）
set -e

# --------------------------------------------------------------------------- #
# 1. 参数校验                                                                  #
# --------------------------------------------------------------------------- #
PGHOST="${PGHOST:-geoflow-postgres}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-geo_user}"
PGDATABASE="${PGDATABASE:-geo_flow}"
MONITOR_DB_USER="${MONITOR_DB_USER:-monitor_user}"

if [ -z "$MONITOR_DB_PASSWORD" ]; then
    echo "ERROR: MONITOR_DB_PASSWORD 环境变量未设置（不硬编码密码）" >&2
    echo "用法: MONITOR_DB_PASSWORD=xxx bash deploy/scripts/setup-db-roles.sh" >&2
    exit 1
fi

# 角色名校验（防 SQL 注入——角色名是标识符，直接拼进 SQL）
if ! [[ "$MONITOR_DB_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
    echo "ERROR: MONITOR_DB_USER 含非法字符（仅允许字母/数字/下划线，首字符非数字）: $MONITOR_DB_USER" >&2
    exit 1
fi

# PGUSER 同样拼进 SQL 标识符位置（ALTER DEFAULT PRIVILEGES FOR ROLE ${PGUSER}），
# 做同样的标识符校验保持一致（审查 B2：与 MONITOR_DB_USER 校验对齐）
if ! [[ "$PGUSER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]]; then
    echo "ERROR: PGUSER 含非法字符（仅允许字母/数字/下划线，首字符非数字）: $PGUSER" >&2
    exit 1
fi

# PGPASSWORD 由环境变量提供（geo_user 的密码）
if [ -z "$PGPASSWORD" ]; then
    echo "ERROR: PGPASSWORD 环境变量未设置（geo_user 的密码）" >&2
    exit 1
fi

PSQL="psql -v ON_ERROR_STOP=1 -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE"

echo "=== 创建 DB 角色: ${MONITOR_DB_USER} @ ${PGHOST}:${PGPORT}/${PGDATABASE} ==="
echo "    DB owner: ${PGUSER}"

# --------------------------------------------------------------------------- #
# 2. 幂等创建角色（已存在则跳过）                                              #
# --------------------------------------------------------------------------- #
# 不吞 stderr：让 PG 连接错误显式暴露（审查次要 1）；|| true 防 set -e 在角色
# 查询无返回时退出（查询本身不报错，空返回是正常分支）
ROLE_EXISTS=$($PSQL -tAc "SELECT 1 FROM pg_roles WHERE rolname='${MONITOR_DB_USER}'" || true)
if [ "$ROLE_EXISTS" != "1" ]; then
    $PSQL -c "CREATE ROLE ${MONITOR_DB_USER} LOGIN;"
    echo "    ✓ 已创建角色 ${MONITOR_DB_USER}（LOGIN）"
else
    echo "    • 角色 ${MONITOR_DB_USER} 已存在，跳过创建"
fi

# --------------------------------------------------------------------------- #
# 3. 设置密码 + 授权                                                           #
#    密码用 psql 变量 :'monitor_pass' 安全替换（处理特殊字符，防注入）         #
#    角色名已通过正则校验，安全拼进 GRANT                                       #
# --------------------------------------------------------------------------- #
$PSQL -v monitor_pass="$MONITOR_DB_PASSWORD" <<EOSQL
    -- 更新 / 设置密码（幂等）
    ALTER ROLE ${MONITOR_DB_USER} PASSWORD :'monitor_pass';

    -- public schema：USAGE（可访问）+ SELECT（只读 GEOFlow 数据）
    -- 不授 CREATE → monitor_user 不能在 public 建表/改 schema
    GRANT USAGE ON SCHEMA public TO ${MONITOR_DB_USER};
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${MONITOR_DB_USER};

    -- monitor schema：USAGE（可访问）+ ALL ON TABLES/SEQUENCES（读写自己的数据）
    -- 不授 CREATE → DDL 留给 alembic（以 geo_user 运行）
    GRANT USAGE ON SCHEMA monitor TO ${MONITOR_DB_USER};
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA monitor TO ${MONITOR_DB_USER};
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA monitor TO ${MONITOR_DB_USER};

    -- ALTER DEFAULT PRIVILEGES：geo_user 未来新建的表自动继承权限
    -- public 新表 → 自动 GRANT SELECT（未来 GEOFlow migration 新增表无需手动授权）
    ALTER DEFAULT PRIVILEGES FOR ROLE ${PGUSER} IN SCHEMA public
        GRANT SELECT ON TABLES TO ${MONITOR_DB_USER};
    -- monitor 新表 → 自动 GRANT ALL（未来 alembic 新增表无需手动授权）
    ALTER DEFAULT PRIVILEGES FOR ROLE ${PGUSER} IN SCHEMA monitor
        GRANT ALL ON TABLES TO ${MONITOR_DB_USER};
    ALTER DEFAULT PRIVILEGES FOR ROLE ${PGUSER} IN SCHEMA monitor
        GRANT ALL ON SEQUENCES TO ${MONITOR_DB_USER};
EOSQL

echo "    ✓ 密码已设置"
echo "    ✓ public schema: USAGE + SELECT（只读）"
echo "    ✓ monitor schema: USAGE + ALL ON TABLES/SEQUENCES（读写）"
echo "    ✓ ALTER DEFAULT PRIVILEGES 已配置（geo_user 新表自动继承）"
echo ""
echo "=== 完成：${MONITOR_DB_USER} 已配置（public 只读 / monitor 读写）==="
echo ""
echo "启用方式（监测系统侧）："
echo "  在 index-monitor 的环境变量中设置："
echo "    MONITOR_DB_USER=${MONITOR_DB_USER}"
echo "    MONITOR_DB_PASSWORD=<同上密码>"
echo "  config.py 会自动重建 DATABASE_URL 使用此用户。"
