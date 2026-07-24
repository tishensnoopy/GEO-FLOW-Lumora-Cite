#!/bin/bash
# deploy/scripts/deploy-lumora-cite.sh
# lumora-cite 集成部署脚本：上传代码 → 添加 DB 配置 → 重建镜像 → 验证
#
# 使用方式（在本地项目根目录执行）：
#   SERVER_PASSWORD=你的服务器密码 bash deploy/scripts/deploy-lumora-cite.sh
#
# 或如果已配置 SSH 密钥：
#   bash deploy/scripts/deploy-lumora-cite.sh
#
# 前置条件：
#   - 本地 Docker 环境测试通过（pytest 16/16 + API 测试 + npm build）
#   - 服务器 124.220.33.188 可达，/opt/geo-monitoring 目录存在

set -euo pipefail

SERVER_IP="124.220.33.188"
SERVER_USER="ubuntu"
REMOTE_DIR="/opt/geo-monitoring"
PROJECT_DIR="/home/tishensnoopy/GEO FLOW+LUMORA CITE"

# ------------------------------------------------------------------
# AI API Key 安全读取：优先从环境变量，其次从 .env.prod 加载
# 禁止在本脚本中硬编码任何真实 API Key
# ------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_PROD_FILE="$PROJECT_DIR/.env.prod"

if [[ -z "${DEEPSEEK_API_KEY:-}" && -f "$ENV_PROD_FILE" ]]; then
    # 从 .env.prod 中读取 DEEPSEEK_API_KEY（不 source 整个文件，避免副作用）
    # tr -d "\"'" 用于去除值两侧可能存在的单/双引号
    DEEPSEEK_API_KEY="$(grep -E '^DEEPSEEK_API_KEY=' "$ENV_PROD_FILE" | head -1 | cut -d'=' -f2- | tr -d "\"'" || true)"
fi

# 校验：必须设置且不能是占位符
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
    echo "❌ 错误：DEEPSEEK_API_KEY 未设置。"
    echo "   请在 $ENV_PROD_FILE 中配置 DEEPSEEK_API_KEY=sk-xxx"
    echo "   或通过环境变量传入：DEEPSEEK_API_KEY=sk-xxx bash $0"
    exit 1
fi
if [[ "$DEEPSEEK_API_KEY" == *"请替换"* || "$DEEPSEEK_API_KEY" == *"your_"* || "$DEEPSEEK_API_KEY" == *"sk-xxx"* ]]; then
    echo "❌ 错误：DEEPSEEK_API_KEY 仍为占位符（$DEEPSEEK_API_KEY），请先在 .env.prod 中填入真实 Key。"
    exit 1
fi

# SSH/SCP 传输方式
if [[ -n "${SERVER_PASSWORD:-}" ]]; then
    SSH_CMD="sshpass -p $SERVER_PASSWORD ssh -o StrictHostKeyChecking=no"
    SCP_CMD="sshpass -p $SERVER_PASSWORD scp -o StrictHostKeyChecking=no"
else
    SSH_CMD="ssh -o StrictHostKeyChecking=no"
    SCP_CMD="scp -o StrictHostKeyChecking=no"
fi

echo "=========================================="
echo "  lumora-cite 集成部署到生产环境"
echo "  服务器: $SERVER_USER@$SERVER_IP"
echo "  远程目录: $REMOTE_DIR"
echo "=========================================="
echo ""

# ------------------------------------------------------------------
# Step 1: 上传新文件和修改文件
# ------------------------------------------------------------------
echo "[1/5] 上传文件到生产服务器..."

# 创建远程目录（citation_check 不存在）
$SSH_CMD $SERVER_USER@$SERVER_IP "mkdir -p $REMOTE_DIR/index-monitor/app/services/citation_check"

# 新目录：citation_check 包（12 文件）
echo "  → citation_check 包 (12 files)..."
$SCP_CMD -r "$PROJECT_DIR/index-monitor/app/services/citation_check/"* \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/services/citation_check/

# 新文件：llm_client.py + citation_checker.py
echo "  → llm_client.py + citation_checker.py..."
$SCP_CMD "$PROJECT_DIR/index-monitor/app/services/llm_client.py" \
         "$PROJECT_DIR/index-monitor/app/services/citation_checker.py" \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/services/

# 修改文件：routes.py
echo "  → routes.py..."
$SCP_CMD "$PROJECT_DIR/index-monitor/app/api/routes.py" \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/index-monitor/app/api/

# 修改文件：init-db.sh
echo "  → init-db.sh..."
$SCP_CMD "$PROJECT_DIR/deploy/scripts/init-db.sh" \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/deploy/scripts/

# 修改文件：Settings.vue + ArticleModal.vue
echo "  → Settings.vue + ArticleModal.vue..."
$SCP_CMD "$PROJECT_DIR/dashboard/src/views/Settings.vue" \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/dashboard/src/views/
$SCP_CMD "$PROJECT_DIR/dashboard/src/components/ArticleModal.vue" \
    $SERVER_USER@$SERVER_IP:$REMOTE_DIR/dashboard/src/components/

echo "  ✅ 文件上传完成"
echo ""

# ------------------------------------------------------------------
# Step 2: 添加 AI 配置项到生产 DB
# ------------------------------------------------------------------
echo "[2/5] 添加 AI 配置项到生产数据库..."

$SSH_CMD $SERVER_USER@$SERVER_IP "docker exec -i geo-postgres psql -U geo_user -d geo_monitoring << 'SQL'
INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
('ai_deepseek_api_key', '$DEEPSEEK_API_KEY', 'string', 'DeepSeek API Key'),
('ai_dashscope_api_key', '', 'string', 'DashScope API Key'),
('ai_ark_api_key', '', 'string', 'ARK API Key'),
('ai_baidu_api_key', '', 'string', 'Baidu API Key'),
('ai_openai_api_key', '', 'string', 'OpenAI API Key'),
('ai_gemini_api_key', '', 'string', 'Gemini API Key'),
('ai_anthropic_api_key', '', 'string', 'Anthropic API Key'),
('ai_question_model', 'deepseek-chat', 'string', 'Question model'),
('ai_citation_models', '', 'string', 'Citation models')
ON CONFLICT (config_key) DO NOTHING;
SQL"

echo "  ✅ AI 配置项已添加"
echo ""

# ------------------------------------------------------------------
# Step 3: 重建 Docker 镜像（必须用 -f docker-compose.prod.yml）
# ------------------------------------------------------------------
echo "[3/5] 重建 index-monitor + dashboard Docker 镜像..."

$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml build index-monitor dashboard 2>&1 | tail -10"

echo "  ✅ 镜像重建完成"
echo ""

# ------------------------------------------------------------------
# Step 4: 重启容器（必须用 -f docker-compose.prod.yml）
# ------------------------------------------------------------------
echo "[4/5] 重启所有容器..."

$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml up -d 2>&1"

echo "  等待容器启动..."
sleep 5

# 检查容器状态
$SSH_CMD $SERVER_USER@$SERVER_IP "cd $REMOTE_DIR && \
    docker compose -f docker-compose.prod.yml ps --format 'table {{.Name}}\t{{.Status}}' 2>/dev/null | head -10"

echo "  ✅ 容器已重启"
echo ""

# ------------------------------------------------------------------
# Step 5: 验证
# ------------------------------------------------------------------
echo "[5/5] 验证部署..."

# 健康检查
echo "  → 健康检查..."
$SSH_CMD $SERVER_USER@$SERVER_IP "curl -s http://localhost:8090/health" && echo ""

# 登录获取 token
echo "  → 登录测试..."
TOKEN=$($SSH_CMD $SERVER_USER@$SERVER_IP \
    "curl -s http://localhost:8090/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{\"username\":\"admin\",\"password\":\"Admin@2026\"}'" | \
    python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [[ -n "$TOKEN" ]]; then
    echo "    ✅ 登录成功，Token: ${TOKEN:0:20}..."

    # 检查 /config 是否包含 AI 配置
    echo "  → /config AI 配置检查..."
    $SSH_CMD $SERVER_USER@$SERVER_IP "curl -s http://localhost:8090/api/v1/config \
        -H 'Authorization: Bearer $TOKEN'" | \
        python3 -c "
import sys,json
data=json.load(sys.stdin)
ai_keys = [k for k in data if k.startswith('ai_')]
for k in ai_keys:
    print(f'    {k}: {data[k]}')
" 2>/dev/null

    # 检查 /citations 端点
    echo "  → /citations 端点检查..."
    $SSH_CMD $SERVER_USER@$SERVER_IP "curl -s http://localhost:8090/api/v1/citations \
        -H 'Authorization: Bearer $TOKEN'"
    echo ""

    # 检查 /articles 是否包含 citation_status
    echo "  → /articles citation_status 检查..."
    $SSH_CMD $SERVER_USER@$SERVER_IP "curl -s http://localhost:8090/api/v1/articles \
        -H 'Authorization: Bearer $TOKEN'" | \
        python3 -c "
import sys,json
data=json.load(sys.stdin)
if not data:
    print('    (空列表)')
else:
    for a in data[:3]:
        print(f'    url={a[\"url\"][:40]}, citation_status={a.get(\"citation_status\")}, total={a.get(\"citation_total\")}')
" 2>/dev/null
else
    echo "    ❌ 登录失败"
fi

# HTTPS 检查
echo "  → HTTPS 检查..."
$SSH_CMD $SERVER_USER@$SERVER_IP "curl -sk -o /dev/null -w '%{http_code}' https://localhost/" && echo " (HTTPS)"
$SSH_CMD $SERVER_USER@$SERVER_IP "curl -s -o /dev/null -w '%{http_code}' http://localhost/" && echo " (HTTP)"

echo ""
echo "=========================================="
echo "  部署完成！"
echo "  Dashboard: https://zkeeeai.com/"
echo "  API: https://zkeeeai.com/api/v1/"
echo "  登录: admin / Admin@2026"
echo "=========================================="
echo ""
echo "  下一步："
echo "  1. 在系统设置中配置 DashScope/ARK 等 API Key（引用检测用）"
echo "  2. 添加真实文章 URL 到 article_distributions 表"
echo "  3. 触发 AI 采信扫描（/scan/trigger/citation 或 /citations/check）"
