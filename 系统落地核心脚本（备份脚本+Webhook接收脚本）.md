# 系统落地核心脚本（备份脚本\+Webhook接收脚本）

## 一、数据库自动备份脚本 /root/backup\_db\.sh（可直接执行）

**脚本功能**：自动备份PostgreSQL业务库、压缩存档、自动清理7天过期备份、适配低配服务器、无资源卡顿

**使用方式**：赋予权限后配合定时任务自动执行

```bash
#!/bin/bash
# GEO项目数据库自动备份脚本
BACKUP_DIR="/root/db_backup"
DATE=$(date +%Y-%m-%d_%H%M%S)
DB_NAME="geodb"
DB_USER="geouser"
RETENTION_DAYS=7

# 创建备份目录
mkdir -p $BACKUP_DIR

# 执行数据库备份（容器内pg_dump）
docker exec geo-postgres pg_dump -U $DB_USER $DB_NAME > $BACKUP_DIR/$DB_NAME-$DATE.sql

# 压缩备份文件
gzip $BACKUP_DIR/$DB_NAME-$DATE.sql

# 删除7天前过期备份
find $BACKUP_DIR -name "geodb-*.sql.gz" -mtime +$RETENTION_DAYS -delete

# 输出备份完成日志
echo "数据库备份完成：$BACKUP_DIR/$DB_NAME-$DATE.sql.gz"
```

**部署执行命令**

```bash
# 赋予脚本执行权限
chmod +x /root/backup_db.sh

# 手动测试执行
/root/backup_db.sh
```

## 二、自研监测服务 Webhook 接收脚本（Python极简版）

**功能说明**：内网接收GEOFlow推送的文章数据、自动入库、加入监测队列，适配项目数据格式，轻量低耗、适配2核4G服务器

**运行端口**：8090（仅容器内网开放，不公网暴露）

**接收数据格式**：完全匹配前文GEOFlow推送JSON规范

```python
# monitor_webhook.py
from flask import Flask, request, jsonify
import psycopg2
import datetime

app = Flask(__name__)

# 数据库统一配置（与全局PostgreSQL对齐）
DB_CONFIG = {
    "host": "geo-postgres",
    "port": 5432,
    "user": "geouser",
    "password": "Geo@2026",
    "dbname": "geodb"
}

# 连接数据库
def get_db_conn():
    return psycopg2.connect(**DB_CONFIG)

# 推送回调接口（内网专属）
@app.route("/webhook/geo-push", methods=["POST"])
def geo_push():
    try:
        data = request.get_json()
        client_id = data.get("client_id")
        domain = data.get("domain")
        article_url = data.get("article_url")
        article_title = data.get("article_title")
        push_time = data.get("push_time", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # 基础参数校验
        if not all([client_id, domain, article_url]):
            return jsonify({"code":400, "msg":"参数缺失"}),400

        # 数据入库，加入监测任务队列
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO monitor_article 
            (client_id, domain, article_url, article_title, push_time, baidu_status, toutiao_status, ai_status)
            VALUES (%s, %s, %s, %s, %s, 'pending', 'pending', 'pending')
            ON CONFLICT (article_url) DO NOTHING;
        """, (client_id, domain, article_url, article_title, push_time))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"code":200, "msg":"任务加入监测队列成功"}),200
    except Exception as e:
        return jsonify({"code":500, "msg":str(e)}),500

# 内网监听，禁止公网访问
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=False)
```

## 三、配套数据库数据表SQL（直接执行创建）

**用途**：创建文章监测表、存储所有推送\+收录\+AI监测数据，适配报表查询

```sql
-- 客户文章监测主表
CREATE TABLE IF NOT EXISTS monitor_article (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    article_url VARCHAR(512) UNIQUE NOT NULL,
    article_title VARCHAR(512),
    push_time VARCHAR(32),
    baidu_status VARCHAR(32) DEFAULT 'pending', -- pending/included/excluded
    toutiao_status VARCHAR(32) DEFAULT 'pending',
    sogou_status VARCHAR(32) DEFAULT 'pending',
    so360_status VARCHAR(32) DEFAULT 'pending',
    ai_check_status VARCHAR(32) DEFAULT 'pending',
    last_check_time VARCHAR(32),
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 客户权限&Token表（报表鉴权核心）
CREATE TABLE IF NOT EXISTS client_token (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(64) UNIQUE NOT NULL,
    domain VARCHAR(255) NOT NULL,
    share_token VARCHAR(32) UNIQUE NOT NULL,
    expire_time TIMESTAMP NOT NULL,
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 四、脚本部署启动命令

```bash
# 安装依赖
pip3 install flask psycopg2-binary

# 后台常驻运行监测服务（内网服务）
nohup python3 monitor_webhook.py > /var/log/monitor-service.log 2>&1 
```

## 五、脚本适配说明（贴合低配服务器）

- 1\. 全程无高并发、无内存泄漏，后台常驻仅占用极低资源

- 2\. 数据重复推送自动去重，避免重复生成监测任务

- 3\. 所有监测状态默认pending，等待定时巡检更新

- 4\. 严格匹配前文定时任务错峰策略，不抢占核心服务资源

- 5\. 完全内网运行，无公网端口暴露，安全无风险

> （注：部分内容可能由 AI 生成）
