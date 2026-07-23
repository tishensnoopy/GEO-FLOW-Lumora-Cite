#!/bin/bash
# deploy/scripts/backup.sh
# 数据库备份脚本（crontab 每周日 04:00 执行）
# 用法：0 4 * * 0 /opt/geo-monitoring/deploy/scripts/backup.sh
set -e

BACKUP_DIR=/opt/geo-monitoring/db_backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/geo_monitoring_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# 从 docker 容器导出数据库（pg_dump + gzip 压缩）
docker exec geo-postgres pg_dump -U geo_user geo_monitoring 2>/dev/null | gzip > "${BACKUP_FILE}"

# 保留最近 30 天备份
find "${BACKUP_DIR}" -name "geo_monitoring_*.sql.gz" -mtime +30 -delete

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 备份完成: ${BACKUP_FILE} ($(du -h ${BACKUP_FILE} | cut -f1))"
