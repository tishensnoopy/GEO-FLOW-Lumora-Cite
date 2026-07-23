#!/bin/bash
# =============================================================================
# seed-test-data.sh
# -----------------------------------------------------------------------------
# 用途：为本地集成测试环境种子化测试数据（clients / client_sites /
#       article_distributions 各 1 条）。
#
# ⚠️  仅用于本地集成测试！生产环境严禁执行！
#     - 测试客户密码为明文 'testpass'（hash 已硬编码，但明文已知）
#     - 测试数据为占位假数据，不能进入生产库
#
# 幂等说明：
#   - 本脚本可重复执行，不会产生重复数据，不会报错。
#   - clients 表：通过 username 唯一约束触发 ON CONFLICT DO UPDATE。
#   - client_sites 表：通过 (client_id, domain) 唯一约束触发 ON CONFLICT DO UPDATE。
#   - article_distributions 表：⚠️ 该表无 article_id 唯一约束（init-db.sh 仅在
#     remote_url 上建立了普通索引，非唯一），无法使用 ON CONFLICT (article_id)。
#     因此采用事务内 DELETE-then-INSERT 模式保证幂等：每次执行先按 article_id
#     删除旧行，再插入新行，最终表中该 article_id 恒为 1 条。
#
# 依赖：
#   - docker 容器 geo-postgres-local 已启动且 healthy
#   - DB geo_monitoring 已由 init-db.sh 初始化（含 7 张表）
#
# 用法：
#   bash deploy/scripts/seed-test-data.sh
# =============================================================================
set -euo pipefail

# ---- 配置 --------------------------------------------------------------------
POSTGRES_CONTAINER="geo-postgres-local"
DB_USER="geo_user"
DB_NAME="geo_monitoring"

PSQL_CMD=(docker exec -i "${POSTGRES_CONTAINER}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1)

# ---- 测试数据 ---------------------------------------------------------------
# password_hash 是 'testpass' 的真实 bcrypt 哈希（成本因子 12），
# 通过 docker exec geo-index-monitor-local python -c "from app.core.security
# import hash_password; print(hash_password('testpass'))" 生成。
# ⚠️ 修改明文密码时必须重新生成 hash 并替换此处。
TESTPASS_BCRYPT_HASH='$2b$12$zGVFJ2syiI1JbGk5pjpRPu8UBUmkiVGZXiI1d2aKg85RFl52kmaqG'

CLIENT_ID="test_client_001"
CLIENT_USERNAME="testuser"
CLIENT_COMPANY="测试客户公司"
CLIENT_STATUS="active"

SITE_NAME="测试官网"
SITE_DOMAIN="example.com"
SITE_TYPE="official"

ARTICLE_ID="art_001"
ARTICLE_URL="https://example.com/test-article-1"
ARTICLE_STATUS="synced"

# ---- 执行 -------------------------------------------------------------------
echo "[seed] 开始写入测试数据 (clients / client_sites / article_distributions)..."

"${PSQL_CMD[@]}" <<SQL
-- 1) clients：username 唯一冲突 → ON CONFLICT DO UPDATE
INSERT INTO clients (
    client_id,
    username,
    password_hash,
    company_name,
    status
) VALUES (
    '${CLIENT_ID}',
    '${CLIENT_USERNAME}',
    '${TESTPASS_BCRYPT_HASH}',
    '${CLIENT_COMPANY}',
    '${CLIENT_STATUS}'
)
ON CONFLICT (username) DO UPDATE SET
    client_id     = EXCLUDED.client_id,
    password_hash = EXCLUDED.password_hash,
    company_name  = EXCLUDED.company_name,
    status        = EXCLUDED.status,
    updated_at    = CURRENT_TIMESTAMP;

-- 2) client_sites：(client_id, domain) 唯一冲突 → ON CONFLICT DO UPDATE
INSERT INTO client_sites (
    client_id,
    site_name,
    domain,
    site_type
) VALUES (
    '${CLIENT_ID}',
    '${SITE_NAME}',
    '${SITE_DOMAIN}',
    '${SITE_TYPE}'
)
ON CONFLICT (client_id, domain) DO UPDATE SET
    site_name  = EXCLUDED.site_name,
    site_type  = EXCLUDED.site_type,
    updated_at = CURRENT_TIMESTAMP;

-- 3) article_distributions：无 article_id 唯一约束，事务内 DELETE + INSERT
BEGIN;
DELETE FROM article_distributions WHERE article_id = '${ARTICLE_ID}';
INSERT INTO article_distributions (
    article_id,
    client_id,
    remote_url,
    status
) VALUES (
    '${ARTICLE_ID}',
    '${CLIENT_ID}',
    '${ARTICLE_URL}',
    '${ARTICLE_STATUS}'
);
COMMIT;
SQL

echo "[seed] 完成。"
echo "[seed] 当前数据计数："
"${PSQL_CMD[@]}" -c "SELECT 'clients' AS table_name, COUNT(*) FROM clients
UNION ALL SELECT 'client_sites', COUNT(*) FROM client_sites
UNION ALL SELECT 'article_distributions', COUNT(*) FROM article_distributions
ORDER BY table_name;"
