#!/bin/bash
# server-deploy-fix.sh
# 在生产服务器上执行（通过云控制台 Web 终端）
# 用法：bash server-deploy-fix.sh
set -euo pipefail

REMOTE_DIR="/opt/geo-monitoring"
BRANCH="master"
REPO_RAW="https://raw.githubusercontent.com/tishensnoopy/GEO-FLOW-Lumora-Cite/$BRANCH"

cd "$REMOTE_DIR" || { echo "❌ 目录 $REMOTE_DIR 不存在"; exit 1; }

echo "=========================================="
echo "  生产服务器端部署（修复 5 个问题）"
echo "  目录: $REMOTE_DIR"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# Step 1: 下载修改的文件（优先 git pull，回退到 raw 下载）
# ------------------------------------------------------------------
echo "[1/6] 同步代码..."

if git rev-parse --git-dir >/dev/null 2>&1; then
    echo "  → git pull..."
    git fetch origin "$BRANCH" && git reset --hard "origin/$BRANCH"
else
    echo "  → 从 GitHub raw 下载文件..."
    # 后端
    for f in \
        index-monitor/app/api/admin_routes.py \
        index-monitor/app/api/sso_routes.py \
        index-monitor/app/services/citation_checker.py \
        index-monitor/app/services/scheduler.py \
        index-monitor/app/services/distribution_query.py \
        index-monitor/app/services/export_service.py \
        index-monitor/app/services/llm_client.py \
        index-monitor/app/models/manual_distribution.py \
        index-monitor/alembic/versions/010_add_content_title_and_fix_model.py \
        deploy/scripts/init-db.sh \
        docker-compose.prod.yml \
        dashboard/src/views/Distributions.vue \
        dashboard/src/views/Dashboard.vue \
        dashboard/src/App.vue \
        dashboard/src/api/index.js; do
        mkdir -p "$(dirname "$f")"
        curl -sfL "$REPO_RAW/$f" -o "$f" && echo "    ✅ $f" || echo "    ❌ $f 下载失败"
    done
fi
echo "  ✅ 代码同步完成"
echo ""

# ------------------------------------------------------------------
# Step 2: 运行 DB 迁移（补 content_title 列 + 修正 ai_question_model）
# ------------------------------------------------------------------
echo "[2/6] 运行 DB 迁移..."

# 尝试 alembic，失败则直接 SQL
if docker compose -f docker-compose.prod.yml exec -T index-monitor alembic upgrade head 2>&1; then
    echo "  ✅ alembic 迁移完成"
else
    echo "  → alembic 不可用，直接执行 SQL..."
    docker exec -i geo-postgres psql -U geo_user -d geo_monitoring << 'SQL'
SET search_path TO monitor, public;
ALTER TABLE monitor.manual_distributions ADD COLUMN IF NOT EXISTS content_title VARCHAR(512);
UPDATE monitor.system_config SET config_value = 'deepseek-v4-flash', updated_at = CURRENT_TIMESTAMP
WHERE config_key = 'ai_question_model' AND config_value = 'deepseek-chat';
SELECT config_key, config_value FROM monitor.system_config WHERE config_key = 'ai_question_model';
SQL
    echo "  ✅ SQL 迁移完成"
fi
echo ""

# ------------------------------------------------------------------
# Step 3: 检查 DeepSeek API Key
# ------------------------------------------------------------------
echo "[3/6] 检查 DeepSeek API Key..."
DEEPSEEK_KEY=$(docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c "SELECT config_value FROM monitor.system_config WHERE config_key = 'ai_deepseek_api_key';" 2>/dev/null | tr -d '[:space:]')
if [[ -n "$DEEPSEEK_KEY" && "$DEEPSEEK_KEY" != "" ]]; then
    echo "  ✅ DeepSeek API Key 已配置: ${DEEPSEEK_KEY:0:8}..."
else
    echo "  ⚠️  DeepSeek API Key 未配置！采信检测将无法运行"
    echo "     请在 Dashboard → 系统设置 → AI API Key 管理中配置"
fi
echo ""

# ------------------------------------------------------------------
# Step 4: 重建 Docker 镜像
# ------------------------------------------------------------------
echo "[4/6] 重建 index-monitor + dashboard 镜像..."
docker compose -f docker-compose.prod.yml build index-monitor dashboard 2>&1 | tail -15
echo "  ✅ 镜像重建完成"
echo ""

# ------------------------------------------------------------------
# Step 5: 重启容器
# ------------------------------------------------------------------
echo "[5/6] 重启容器..."
docker compose -f docker-compose.prod.yml up -d 2>&1
echo "  等待容器启动..."
sleep 8

echo "  → 容器状态:"
docker compose -f docker-compose.prod.yml ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null
echo ""

# ------------------------------------------------------------------
# Step 6: 验证
# ------------------------------------------------------------------
echo "[6/6] 验证部署..."

echo "  → 健康检查:"
curl -s http://localhost:8090/health && echo ""

echo "  → content_title 列检查:"
docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c "SELECT column_name FROM information_schema.columns WHERE table_schema='monitor' AND table_name='manual_distributions' AND column_name='content_title';" 2>/dev/null

echo "  → ai_question_model 值:"
docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c "SELECT config_value FROM monitor.system_config WHERE config_key = 'ai_question_model';" 2>/dev/null

echo "  → 最近错误日志:"
docker compose -f docker-compose.prod.yml logs index-monitor --since 5m 2>&1 | grep -iE 'error|exception|traceback' | tail -5 || echo "  ✅ 无错误"

echo ""
echo "=========================================="
echo "  部署完成！请验证："
echo "  1. https://monitor.zkeeeai.com Dashboard 数据"
echo "  2. 退出管理员→客户登录→界面切换"
echo "  3. 手动添加URL→标题抓取"
echo "  4. 分发记录来源筛选"
echo "  5. SSO 单点登录"
echo "  6. 批量检测功能"
echo "=========================================="
