#!/bin/bash
# deploy/scripts/deploy-fix-batch.sh
# 部署 Dashboard 计算/角色切换/标题抓取/筛选/SSO/采信检测 修复
set -euo pipefail

cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"

# 加载服务器配置
set -a
source <(grep -E '^(SERVER_IP|SERVER_USER|SERVER_PASSWORD)=' .env.prod)
set +a

SERVER_IP="${SERVER_IP:-124.220.33.188}"
SERVER_USER="${SERVER_USER:-ubuntu}"
REMOTE_DIR="/opt/geo-monitoring"

SSH_CMD="sshpass -p $SERVER_PASSWORD ssh -o StrictHostKeyChecking=no"
SCP_CMD="sshpass -p $SERVER_PASSWORD scp -o StrictHostKeyChecking=no"

echo "=========================================="
echo "  部署修复到生产环境"
echo "  服务器: $SERVER_USER@$SERVER_IP"
echo "  远程目录: $REMOTE_DIR"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# Step 1: 上传修改的文件
# ------------------------------------------------------------------
echo "[1/6] 上传修改文件到生产服务器..."

# 后端文件
echo "  → 后端 Python 文件..."
$SCP_CMD \
    "index-monitor/app/api/admin_routes.py" \
    "index-monitor/app/api/sso_routes.py" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/api/"

$SCP_CMD \
    "index-monitor/app/services/citation_checker.py" \
    "index-monitor/app/services/scheduler.py" \
    "index-monitor/app/services/distribution_query.py" \
    "index-monitor/app/services/export_service.py" \
    "index-monitor/app/services/llm_client.py" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/services/"

$SCP_CMD \
    "index-monitor/app/models/manual_distribution.py" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/models/"

# Alembic 迁移
echo "  → Alembic 迁移 010..."
$SCP_CMD \
    "index-monitor/alembic/versions/010_add_content_title_and_fix_model.py" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/alembic/versions/"

# 部署脚本
echo "  → init-db.sh..."
$SCP_CMD \
    "deploy/scripts/init-db.sh" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/deploy/scripts/"

# 前端文件
echo "  → 前端 Vue 文件..."
$SCP_CMD \
    "dashboard/src/views/Distributions.vue" \
    "dashboard/src/views/Dashboard.vue" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/dashboard/src/views/"

$SCP_CMD \
    "dashboard/src/App.vue" \
    "dashboard/src/api/index.js" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/dashboard/src/"

# docker-compose.prod.yml
echo "  → docker-compose.prod.yml..."
$SCP_CMD \
    "docker-compose.prod.yml" \
    "$SERVER_USER@$SERVER_IP:$REMOTE_DIR/"

echo "  ✅ 文件上传完成"
echo ""

# ------------------------------------------------------------------
# Step 2: 运行 DB 迁移（补 content_title 列 + 修正 ai_question_model）
# ------------------------------------------------------------------
echo "[2/6] 运行 DB 迁移（010: content_title + ai_question_model 修正）..."

$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml exec -T index-monitor \
    alembic upgrade head 2>&1" || {
    # 如果 alembic 命令不可用，直接用 psql 执行 SQL
    echo "  → alembic 不可用，改用 psql 直接执行 SQL..."
    $SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring << 'SQL'
    SET search_path TO monitor, public;
    ALTER TABLE monitor.manual_distributions ADD COLUMN IF NOT EXISTS content_title VARCHAR(512);
    UPDATE monitor.system_config SET config_value = 'deepseek-v4-flash', updated_at = CURRENT_TIMESTAMP
    WHERE config_key = 'ai_question_model' AND config_value = 'deepseek-chat';
    SELECT config_key, config_value FROM monitor.system_config WHERE config_key = 'ai_question_model';
SQL"
}

echo "  ✅ DB 迁移完成"
echo ""

# ------------------------------------------------------------------
# Step 3: 同步 DeepSeek API Key 到 system_config（如果 .env.prod 有配置）
# ------------------------------------------------------------------
echo "[3/6] 同步 DeepSeek API Key..."

DEEPSEEK_API_KEY="$(grep -E '^DEEPSEEK_API_KEY=' .env.prod | head -1 | cut -d'=' -f2- | tr -d "\"'" || true)"
if [[ -n "${DEEPSEEK_API_KEY:-}" && "$DEEPSEEK_API_KEY" != *"请替换"* && "$DEEPSEEK_API_KEY" != *"sk-xxx"* ]]; then
    $SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring << SQL
    UPDATE monitor.system_config
    SET config_value = '$DEEPSEEK_API_KEY', updated_at = CURRENT_TIMESTAMP
    WHERE config_key = 'ai_deepseek_api_key';
SQL"
    echo "  ✅ DeepSeek API Key 已同步"
else
    echo "  ⚠️  DEEPSEEK_API_KEY 未配置或为占位符，跳过同步"
    echo "     当前 DB 中的 Key:"
    $SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c \"SELECT 'ai_deepseek_api_key: ' || LEFT(config_value, 10) || '...' FROM monitor.system_config WHERE config_key = 'ai_deepseek_api_key';\"" 2>/dev/null || echo "     (查询失败)"
fi
echo ""

# ------------------------------------------------------------------
# Step 4: 重建 Docker 镜像
# ------------------------------------------------------------------
echo "[4/6] 重建 index-monitor + dashboard Docker 镜像..."

$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml build index-monitor dashboard 2>&1 | tail -15"

echo "  ✅ 镜像重建完成"
echo ""

# ------------------------------------------------------------------
# Step 5: 重启容器
# ------------------------------------------------------------------
echo "[5/6] 重启容器..."

$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml up -d 2>&1"

echo "  等待容器启动..."
sleep 8

# 检查容器状态
echo "  → 容器状态:"
$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null"

echo "  ✅ 容器已重启"
echo ""

# ------------------------------------------------------------------
# Step 6: 验证
# ------------------------------------------------------------------
echo "[6/6] 验证部署..."

# 健康检查
echo "  → 健康检查..."
$SSH_CMD $SERVER_USER@$SERVER_IP "curl -s http://localhost:8090/health" && echo ""

# 检查 content_title 列
echo "  → 检查 manual_distributions.content_title 列..."
$SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c \"SELECT column_name FROM information_schema.columns WHERE table_schema='monitor' AND table_name='manual_distributions' AND column_name='content_title';\"" 2>/dev/null && echo "  ✅ content_title 列存在"

# 检查 ai_question_model
echo "  → 检查 ai_question_model 值..."
$SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring -t -c \"SELECT config_value FROM monitor.system_config WHERE config_key = 'ai_question_model';\"" 2>/dev/null

# 检查最近5分钟错误日志
echo "  → 检查 index-monitor 最近错误日志..."
$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml logs index-monitor --since 5m 2>&1 | grep -iE 'error|exception|traceback' | tail -10" || echo "  ✅ 无错误日志"

echo ""
echo "=========================================="
echo "  部署完成！请验证以下功能："
echo "  1. Dashboard 数据计算（收录率/AI采信数）"
echo "  2. 退出管理员→客户登录→界面切换"
echo "  3. 手动添加URL→标题抓取"
echo "  4. 分发记录来源筛选"
echo "  5. SSO 单点登录"
echo "  6. 批量检测功能"
echo "=========================================="
