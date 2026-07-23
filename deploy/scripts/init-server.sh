#!/bin/bash
# deploy/scripts/init-server.sh
# 服务器环境初始化（在云端 124.220.33.188 执行）
set -e

echo "=== 服务器环境初始化 ==="

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装基础依赖
sudo apt install -y curl git vim htop net-tools ufw fail2ban

# 配置防火墙（仅开放 22/80/443）
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# 配置系统参数（Redis 优化）
echo "vm.overcommit_memory=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# 配置日志轮转
sudo tee /etc/logrotate.d/geo << 'EOF'
/var/log/geo-*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    maxsize 100M
}
EOF

echo "=== 初始化完成 ==="
echo "Docker 版本："
docker --version
echo "Docker Compose 版本："
docker compose version
