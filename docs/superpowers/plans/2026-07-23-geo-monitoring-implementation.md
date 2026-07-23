# GEO 内容分发 + 收录 AI 监测系统 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建一个完整的 GEO 内容分发与收录监测系统，实现文章生成、推送、收录检测、AI 采信检测和客户 Dashboard 展示的全链路闭环。

**架构：** 基于 GEOFlow（内容生成）+ 自研收录检测服务（Python）+ lumora-cite（AI 采信检测）+ Vue 3 Dashboard 的四层架构，使用 Docker Compose 编排，PostgreSQL 统一存储，Nginx 反向代理。

**技术栈：** 
- 后端：Laravel 11（GEOFlow）、Python 3.11 + FastAPI（检测服务）、Vue 3 + Element Plus（Dashboard）
- 数据库：PostgreSQL 15 + Redis 7
- 部署：Docker Compose + Nginx
- 服务器：Ubuntu 22.04 LTS（4核4G40GB）

---

## 安全配置

### 服务器凭据管理

**禁止在代码库中存储明文密码！**

1. 创建 `.env` 文件（已添加到 .gitignore）：
```bash
SERVER_IP=124.220.33.188
SERVER_USER=ubuntu
SERVER_PASSWORD=Hym465964665
POSTGRES_PASSWORD=Geo@2026Secure
REDIS_PASSWORD=Redis@2026Secure
JWT_SECRET=your-jwt-secret-here
```

2. 使用 SSH 密钥认证（推荐）：
```bash
ssh-keygen -t ed25519 -C "geo-monitoring"
ssh-copy-id ubuntu@124.220.33.188
```

---

## 文件结构

```
/home/tishensnoopy/GEO FLOW+LUMORA CITE/
├── GEOFlow-main/                          # 内容生成系统（已有）
├── lumora-cite-main/                      # AI 采信检测（已有）
├── index-monitor/                         # 收录检测服务（新建）
│   ├── app/
│   │   ├── main.py                        # FastAPI 入口
│   │   ├── api/
│   │   │   ├── routes.py                  # API 路由
│   │   │   └── deps.py                    # 依赖注入
│   │   ├── core/
│   │   │   ├── config.py                  # 配置管理
│   │   │   ├── security.py                # 安全认证
│   │   │   └── database.py                # 数据库连接
│   │   ├── models/
│   │   │   ├── article.py                 # 文章模型
│   │   │   ├── index_result.py            # 收录结果模型
│   │   │   └── citation_result.py         # AI 采信结果模型
│   │   ├── services/
│   │   │   ├── index_checker.py           # 收录检测逻辑
│   │   │   ├── spider.py                  # 爬虫服务
│   │   │   └── scheduler.py               # 定时任务
│   │   └── utils/
│   │       ├── http_client.py             # HTTP 客户端
│   │       └── logger.py                  # 日志工具
│   ├── tests/
│   │   ├── test_api.py
│   │   ├── test_spider.py
│   │   └── test_scheduler.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml
├── dashboard/                             # 客户 Dashboard（新建）
│   ├── src/
│   │   ├── main.js                        # Vue 入口
│   │   ├── App.vue
│   │   ├── router/
│   │   │   └── index.js                   # 路由配置
│   │   ├── store/
│   │   │   └── index.js                   # Vuex 状态管理
│   │   ├── views/
│   │   │   ├── Login.vue                  # 登录页
│   │   │   ├── Dashboard.vue              # 仪表盘
│   │   │   ├── Articles.vue               # 文章列表
│   │   │   └── Settings.vue               # 系统设置
│   │   ├── components/
│   │   │   ├── IndexChart.vue             # 收录趋势图
│   │   │   ├── CitationChart.vue          # AI 采信图
│   │   │   ├── ArticleCard.vue            # 文章卡片
│   │   │   └── ArticleModal.vue           # 文章详情弹窗
│   │   ├── api/
│   │   │   └── index.js                   # API 调用
│   │   └── utils/
│   │       └── auth.js                    # 认证工具
│   ├── public/
│   │   └── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── Dockerfile
│   └── nginx.conf
├── deploy/                                # 部署配置（新建）
│   ├── docker-compose.yml                 # 主编排文件
│   ├── nginx/
│   │   ├── nginx.conf                     # Nginx 主配置
│   │   └── conf.d/
│   │       ├── geoflow.conf               # GEOFlow 反代
│   │       ├── dashboard.conf             # Dashboard 反代
│   │       └── monitor.conf               # 监控服务反代
│   ├── scripts/
│   │   ├── init-db.sh                     # 数据库初始化
│   │   ├── backup.sh                      # 备份脚本
│   │   └── deploy.sh                      # 部署脚本
│   └── ssl/                               # SSL 证书目录
├── docs/
│   └── superpowers/
│       ├── specs/                         # 设计文档
│       └── plans/                         # 实现计划
└── .env                                   # 环境变量（不提交）
```

---

## 阶段一：基础环境搭建（第 1 天）

### 任务 1：服务器环境初始化

**文件：**
- 创建：`deploy/scripts/init-server.sh`

- [ ] **步骤 1：创建服务器初始化脚本**

```bash
#!/bin/bash
# deploy/scripts/init-server.sh

set -e

echo "=== 服务器环境初始化 ==="

# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装基础依赖
sudo apt install -y \
    curl \
    git \
    vim \
    htop \
    net-tools \
    ufw \
    fail2ban \
    python3-pip

# 配置防火墙
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# 配置系统参数
echo "vm.overcommit_memory=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# 配置日志轮转
cat > /tmp/logrotate-geo << 'EOF'
/var/log/geo-*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    maxsize 100M
}
EOF
sudo mv /tmp/logrotate-geo /etc/logrotate.d/geo

# 配置文件描述符限制
cat >> /etc/security/limits.conf << 'EOF'
* soft nofile 65535
* hard nofile 65535
* soft nproc 16384
* hard nproc 16384
EOF

echo "=== 初始化完成 ==="
```

- [ ] **步骤 2：执行服务器初始化**

```bash
chmod +x deploy/scripts/init-server.sh
ssh ubuntu@124.220.33.188 'bash -s' < deploy/scripts/init-server.sh
```

**验收标准：**
- 系统更新完成
- 防火墙配置正确（仅开放 22/80/443）
- 日志轮转配置生效

---

### 任务 2：Docker 环境验证

**文件：**
- 修改：`deploy/docker-compose.yml`

- [ ] **步骤 1：验证 Docker 环境**

```bash
ssh ubuntu@124.220.33.188
docker --version
docker compose version
docker ps
```

预期输出：
```
Docker version 29.6.1
Docker Compose version v5.3.1
```

- [ ] **步骤 2：创建项目目录结构**

```bash
ssh ubuntu@124.220.33.188
sudo mkdir -p /opt/geo-monitoring
sudo chown ubuntu:ubuntu /opt/geo-monitoring
```

- [ ] **步骤 3：上传项目文件**

```bash
# 从本地上传
rsync -avz --exclude='node_modules' --exclude='vendor' \
  "/home/tishensnoopy/GEO FLOW+LUMORA CITE/" \
  ubuntu@124.220.33.188:/opt/geo-monitoring/
```

**验收标准：**
- Docker 和 Docker Compose 版本正确
- 项目文件上传完成
- 目录权限正确

---

### 任务 3：数据库部署

**文件：**
- 创建：`deploy/docker-compose.db.yml`
- 创建：`deploy/scripts/init-db.sh`

- [ ] **步骤 1：创建数据库 docker-compose 配置**

```yaml
# deploy/docker-compose.db.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: geo-postgres
    restart: always
    environment:
      POSTGRES_DB: geo_monitoring
      POSTGRES_USER: geo_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    ports:
      - "127.0.0.1:5432:5432"
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U geo_user -d geo_monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: geo-redis
    restart: always
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.25'
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  redis_data:
```

- [ ] **步骤 2：创建数据库初始化脚本**

```bash
#!/bin/bash
# deploy/scripts/init-db.sh
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- 创建扩展
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    
    -- 文章分发记录表
    CREATE TABLE IF NOT EXISTS article_distributions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        article_id VARCHAR(255) NOT NULL,
        remote_url VARCHAR(512) NOT NULL,
        status VARCHAR(32) NOT NULL DEFAULT 'synced',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX idx_article_distributions_status ON article_distributions(status);
    CREATE INDEX idx_article_distributions_url ON article_distributions(remote_url);
    
    -- 收录结果表
    CREATE TABLE IF NOT EXISTS index_results (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL UNIQUE,
        client_id VARCHAR(64) NOT NULL,
        site_type VARCHAR(32) NOT NULL,
        content_title VARCHAR(512),
        content_keywords TEXT[],
        content_snapshot TEXT,
        baidu_status VARCHAR(32) DEFAULT 'pending',
        toutiao_status VARCHAR(32) DEFAULT 'pending',
        sogou_status VARCHAR(32) DEFAULT 'pending',
        so360_status VARCHAR(32) DEFAULT 'pending',
        bing_status VARCHAR(32) DEFAULT 'pending',
        baidu_checked_at TIMESTAMP,
        toutiao_checked_at TIMESTAMP,
        sogou_checked_at TIMESTAMP,
        so360_checked_at TIMESTAMP,
        bing_checked_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    CREATE INDEX idx_index_results_client_id ON index_results(client_id);
    CREATE INDEX idx_index_results_site_type ON index_results(site_type);
    CREATE INDEX idx_index_results_baidu_status ON index_results(baidu_status);
    
    -- 收录历史记录表
    CREATE TABLE IF NOT EXISTS index_history (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL,
        check_date DATE NOT NULL,
        baidu_status VARCHAR(32) NOT NULL,
        toutiao_status VARCHAR(32) NOT NULL,
        sogou_status VARCHAR(32) NOT NULL,
        so360_status VARCHAR(32) NOT NULL,
        bing_status VARCHAR(32) NOT NULL,
        total_indexed INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(url, check_date)
    );
    
    CREATE INDEX idx_index_history_url ON index_history(url);
    CREATE INDEX idx_index_history_check_date ON index_history(check_date);
    
    -- AI 采信结果表
    CREATE TABLE IF NOT EXISTS citation_results (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        url VARCHAR(512) NOT NULL,
        model VARCHAR(64) NOT NULL,
        question TEXT NOT NULL,
        answer TEXT,
        hit_type VARCHAR(32) NOT NULL,
        sources JSONB,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(url, model, question)
    );
    
    CREATE INDEX idx_citation_results_url ON citation_results(url);
    CREATE INDEX idx_citation_results_model ON citation_results(model);
    CREATE INDEX idx_citation_results_hit_type ON citation_results(hit_type);
    
    -- 客户表
    CREATE TABLE IF NOT EXISTS clients (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        client_id VARCHAR(64) UNIQUE NOT NULL,
        username VARCHAR(128) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        email VARCHAR(255),
        phone VARCHAR(32),
        company_name VARCHAR(255),
        status VARCHAR(32) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- 客户站点表
    CREATE TABLE IF NOT EXISTS client_sites (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        client_id VARCHAR(64) NOT NULL,
        site_name VARCHAR(255) NOT NULL,
        domain VARCHAR(255) NOT NULL,
        site_type VARCHAR(32) NOT NULL,
        wordpress_api_url VARCHAR(512),
        wordpress_api_token VARCHAR(255),
        status VARCHAR(32) DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(client_id, domain)
    );
    
    CREATE INDEX idx_client_sites_client_id ON client_sites(client_id);
    
    -- 系统配置表
    CREATE TABLE IF NOT EXISTS system_config (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        config_key VARCHAR(128) UNIQUE NOT NULL,
        config_value TEXT NOT NULL,
        config_type VARCHAR(32) NOT NULL,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- 初始化默认配置
    INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
    ('index_scan_frequency', '1', 'number', '收录检测频率（天/次），默认每天 1 次'),
    ('index_scan_time', '02:00', 'string', '收录检测执行时间，默认凌晨 2:00'),
    ('citation_scan_frequency', '7', 'number', 'AI 采信检测频率（天/次），默认每 7 天 1 次'),
    ('citation_scan_time', '03:00', 'string', 'AI 采信检测执行时间，默认凌晨 3:00'),
    ('citation_sample_size', '20', 'number', 'AI 采信检测抽样数量，默认 20 篇'),
    ('spider_concurrent', '3', 'number', '爬虫并发数，默认 3'),
    ('spider_interval_min', '2', 'number', '爬虫最小间隔（秒），默认 2 秒'),
    ('spider_interval_max', '5', 'number', '爬虫最大间隔（秒），默认 5 秒')
    ON CONFLICT (config_key) DO NOTHING;
EOSQL
```

- [ ] **步骤 3：启动数据库服务**

```bash
cd /opt/geo-monitoring/deploy
docker compose -f docker-compose.db.yml up -d
docker compose -f docker-compose.db.yml ps
```

**验收标准：**
- PostgreSQL 和 Redis 容器运行正常
- 数据库表创建成功
- 默认配置插入成功

---

## 阶段二：收录检测服务开发（第 2-3 天）

### 任务 4：FastAPI 基础框架

**文件：**
- 创建：`index-monitor/app/main.py`
- 创建：`index-monitor/app/core/config.py`
- 创建：`index-monitor/app/core/database.py`
- 创建：`index-monitor/requirements.txt`
- 创建：`index-monitor/Dockerfile`

- [ ] **步骤 1：创建 requirements.txt**

```txt
# index-monitor/requirements.txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
sqlalchemy==2.0.25
asyncpg==0.29.0
psycopg2-binary==2.9.9
redis==5.0.1
pydantic==2.5.3
pydantic-settings==2.1.0
python-dotenv==1.0.0
httpx==0.26.0
beautifulsoup4==4.12.3
lxml==5.1.0
apscheduler==3.10.4
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
```

- [ ] **步骤 2：创建配置管理模块**

```python
# index-monitor/app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "Index Monitor Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # 数据库配置
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "geo_monitoring"
    POSTGRES_USER: str = "geo_user"
    POSTGRES_PASSWORD: str
    
    # Redis 配置
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str
    
    # 安全配置
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # 爬虫配置
    SPIDER_CONCURRENT: int = 3
    SPIDER_INTERVAL_MIN: int = 2
    SPIDER_INTERVAL_MAX: int = 5
    
    # 第三方 API
    API_5118_KEY: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
```

- [ ] **步骤 3：创建数据库连接模块**

```python
# index-monitor/app/core/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

DATABASE_URL = f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"

engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)

async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
```

- [ ] **步骤 4：创建 FastAPI 主入口**

```python
# index-monitor/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
```

- [ ] **步骤 5：创建 Dockerfile**

```dockerfile
# index-monitor/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 暴露端口
EXPOSE 8090

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
```

- [ ] **步骤 6：编写测试验证框架**

```python
# index-monitor/tests/test_main.py
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
```

- [ ] **步骤 7：运行测试**

```bash
cd index-monitor
pip install -r requirements.txt
pytest tests/test_main.py -v
```

预期输出：`PASSED`

- [ ] **步骤 8：Commit**

```bash
git add index-monitor/
git commit -m "feat: 初始化收录检测服务 FastAPI 框架"
```

**验收标准：**
- FastAPI 应用启动成功
- 健康检查接口返回 200
- 数据库连接正常
- 测试通过

---

### 任务 5：数据模型定义

**文件：**
- 创建：`index-monitor/app/models/article.py`
- 创建：`index-monitor/app/models/index_result.py`
- 创建：`index-monitor/app/models/citation_result.py`
- 创建：`index-monitor/app/models/client.py`

- [ ] **步骤 1：创建文章分发模型**

```python
# index-monitor/app/models/article.py
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
import uuid

class ArticleDistribution(Base):
    __tablename__ = "article_distributions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_id = Column(String(255), nullable=False)
    remote_url = Column(String(512), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="synced", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 2：创建收录结果模型**

```python
# index-monitor/app/models/index_result.py
from sqlalchemy import Column, String, DateTime, Text, ARRAY, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
import uuid

class IndexResult(Base):
    __tablename__ = "index_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, unique=True, index=True)
    client_id = Column(String(64), nullable=False, index=True)
    site_type = Column(String(32), nullable=False, index=True)
    content_title = Column(String(512))
    content_keywords = Column(ARRAY(Text))
    content_snapshot = Column(Text)
    
    # 各搜索引擎状态
    baidu_status = Column(String(32), default="pending")
    toutiao_status = Column(String(32), default="pending")
    sogou_status = Column(String(32), default="pending")
    so360_status = Column(String(32), default="pending")
    bing_status = Column(String(32), default="pending")
    
    # 各搜索引擎检测时间
    baidu_checked_at = Column(DateTime(timezone=True))
    toutiao_checked_at = Column(DateTime(timezone=True))
    sogou_checked_at = Column(DateTime(timezone=True))
    so360_checked_at = Column(DateTime(timezone=True))
    bing_checked_at = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class IndexHistory(Base):
    __tablename__ = "index_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    check_date = Column(DateTime(timezone=True), nullable=False, index=True)
    baidu_status = Column(String(32), nullable=False)
    toutiao_status = Column(String(32), nullable=False)
    sogou_status = Column(String(32), nullable=False)
    so360_status = Column(String(32), nullable=False)
    bing_status = Column(String(32), nullable=False)
    total_indexed = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 3：创建 AI 采信结果模型**

```python
# index-monitor/app/models/citation_result.py
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.core.database import Base
import uuid

class CitationResult(Base):
    __tablename__ = "citation_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url = Column(String(512), nullable=False, index=True)
    model = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text)
    hit_type = Column(String(32), nullable=False, index=True)
    sources = Column(JSONB)
    checked_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **步骤 4：创建客户模型**

```python
# index-monitor/app/models/client.py
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
import uuid

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), unique=True, nullable=False)
    username = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(32))
    company_name = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ClientSite(Base):
    __tablename__ = "client_sites"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(64), nullable=False, index=True)
    site_name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    site_type = Column(String(32), nullable=False)
    wordpress_api_url = Column(String(512))
    wordpress_api_token = Column(String(255))
    status = Column(String(32), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **步骤 5：编写模型测试**

```python
# index-monitor/tests/test_models.py
from sqlalchemy import select
from app.models.article import ArticleDistribution
from app.models.index_result import IndexResult
from app.core.database import async_session

async def test_models():
    async with async_session() as session:
        # 测试查询文章分发
        result = await session.execute(select(ArticleDistribution).limit(1))
        articles = result.scalars().all()
        assert isinstance(articles, list)
        
        # 测试查询收录结果
        result = await session.execute(select(IndexResult).limit(1))
        index_results = result.scalars().all()
        assert isinstance(index_results, list)
```

- [ ] **步骤 6：运行测试**

```bash
pytest tests/test_models.py -v
```

预期输出：`PASSED`

- [ ] **步骤 7：Commit**

```bash
git add index-monitor/app/models/
git commit -m "feat: 定义收录检测服务数据模型"
```

**验收标准：**
- 所有模型定义正确
- 数据库表映射成功
- 测试通过

---

### 任务 6：爬虫服务实现

**文件：**
- 创建：`index-monitor/app/services/spider.py`
- 创建：`index-monitor/app/utils/http_client.py`

- [ ] **步骤 1：创建 HTTP 客户端工具**

```python
# index-monitor/app/utils/http_client.py
import httpx
import random
from typing import Optional, Dict
from app.core.config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

class HttpClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True
        )
    
    def get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)
    
    async def get(self, url: str, headers: Optional[Dict] = None) -> httpx.Response:
        if headers is None:
            headers = {}
        headers["User-Agent"] = self.get_random_ua()
        
        await self._random_delay()
        return await self.client.get(url, headers=headers)
    
    async def _random_delay(self):
        delay = random.randint(
            settings.SPIDER_INTERVAL_MIN,
            settings.SPIDER_INTERVAL_MAX
        )
        import asyncio
        await asyncio.sleep(delay)
    
    async def close(self):
        await self.client.aclose()

http_client = HttpClient()
```

- [ ] **步骤 2：创建爬虫服务**

```python
# index-monitor/app/services/spider.py
import asyncio
from typing import Dict, List
from bs4 import BeautifulSoup
from app.utils.http_client import http_client
from app.core.config import settings

class IndexSpider:
    """搜索引擎收录检测爬虫"""
    
    def __init__(self):
        self.concurrent_limit = settings.SPIDER_CONCURRENT
        self.semaphore = asyncio.Semaphore(self.concurrent_limit)
    
    async def check_baidu(self, url: str) -> bool:
        """检查百度收录"""
        async with self.semaphore:
            try:
                query_url = f"https://www.baidu.com/s?wd=site:{url}"
                response = await http_client.get(query_url)
                soup = BeautifulSoup(response.text, 'lxml')
                
                # 检查是否有搜索结果
                results = soup.find_all('div', class_='result')
                return len(results) > 0
            except Exception as e:
                print(f"百度检测失败: {url}, 错误: {e}")
                return False
    
    async def check_toutiao(self, url: str) -> bool:
        """检查头条收录"""
        async with self.semaphore:
            try:
                query_url = f"https://so.toutiao.com/search?keyword=site:{url}"
                response = await http_client.get(query_url)
                soup = BeautifulSoup(response.text, 'lxml')
                
                results = soup.find_all('div', class_='result')
                return len(results) > 0
            except Exception as e:
                print(f"头条检测失败: {url}, 错误: {e}")
                return False
    
    async def check_sogou(self, url: str) -> bool:
        """检查搜狗收录"""
        async with self.semaphore:
            try:
                query_url = f"https://www.sogou.com/web?query=site:{url}"
                response = await http_client.get(query_url)
                soup = BeautifulSoup(response.text, 'lxml')
                
                results = soup.find_all('div', class_='rb')
                return len(results) > 0
            except Exception as e:
                print(f"搜狗检测失败: {url}, 错误: {e}")
                return False
    
    async def check_so360(self, url: str) -> bool:
        """检查360收录"""
        async with self.semaphore:
            try:
                query_url = f"https://www.so.com/s?q=site:{url}"
                response = await http_client.get(query_url)
                soup = BeautifulSoup(response.text, 'lxml')
                
                results = soup.find_all('li', class_='res-list')
                return len(results) > 0
            except Exception as e:
                print(f"360检测失败: {url}, 错误: {e}")
                return False
    
    async def check_bing(self, url: str) -> bool:
        """检查必应收录"""
        async with self.semaphore:
            try:
                query_url = f"https://www.bing.com/search?q=site:{url}"
                response = await http_client.get(query_url)
                soup = BeautifulSoup(response.text, 'lxml')
                
                results = soup.find_all('li', class_='b_algo')
                return len(results) > 0
            except Exception as e:
                print(f"必应检测失败: {url}, 错误: {e}")
                return False
    
    async def check_all_engines(self, url: str) -> Dict[str, bool]:
        """检测所有搜索引擎"""
        tasks = [
            self.check_baidu(url),
            self.check_toutiao(url),
            self.check_sogou(url),
            self.check_so360(url),
            self.check_bing(url)
        ]
        
        results = await asyncio.gather(*tasks)
        
        return {
            "baidu": results[0],
            "toutiao": results[1],
            "sogou": results[2],
            "so360": results[3],
            "bing": results[4]
        }

spider = IndexSpider()
```

- [ ] **步骤 3：编写爬虫测试**

```python
# index-monitor/tests/test_spider.py
import pytest
from app.services.spider import spider

@pytest.mark.asyncio
async def test_check_baidu():
    # 测试一个已知被收录的 URL
    result = await spider.check_baidu("https://www.baidu.com")
    assert isinstance(result, bool)

@pytest.mark.asyncio
async def test_check_all_engines():
    result = await spider.check_all_engines("https://www.baidu.com")
    assert isinstance(result, dict)
    assert "baidu" in result
    assert "toutiao" in result
    assert "sogou" in result
    assert "so360" in result
    assert "bing" in result
```

- [ ] **步骤 4：运行测试**

```bash
pytest tests/test_spider.py -v
```

预期输出：`PASSED`

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/services/spider.py index-monitor/app/utils/
git commit -m "feat: 实现搜索引擎收录检测爬虫"
```

**验收标准：**
- 爬虫能正确检测各搜索引擎收录状态
- 并发控制生效
- 随机延迟生效
- 测试通过

---

### 任务 7：定时任务调度器

**文件：**
- 创建：`index-monitor/app/services/scheduler.py`
- 创建：`index-monitor/app/services/index_checker.py`

- [ ] **步骤 1：创建收录检测服务**

```python
# index-monitor/app/services/index_checker.py
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.article import ArticleDistribution
from app.models.index_result import IndexResult, IndexHistory
from app.services.spider import spider

class IndexChecker:
    """收录检测服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spider = spider
    
    async def get_pending_urls(self) -> List[str]:
        """获取待检测的 URL 列表"""
        # 查询已分发的文章
        result = await self.db.execute(
            select(ArticleDistribution.remote_url)
            .where(ArticleDistribution.status == "synced")
        )
        distributed_urls = [row[0] for row in result.fetchall()]
        
        # 查询已检测的 URL
        result = await self.db.execute(
            select(IndexResult.url)
        )
        checked_urls = [row[0] for row in result.fetchall()]
        
        # 返回未检测的 URL
        return list(set(distributed_urls) - set(checked_urls))
    
    async def check_url(self, url: str, client_id: str, site_type: str):
        """检测单个 URL 的收录状态"""
        # 调用爬虫检测所有搜索引擎
        results = await self.spider.check_all_engines(url)
        
        # 构建更新数据
        update_data = {
            "url": url,
            "client_id": client_id,
            "site_type": site_type,
            "baidu_status": "indexed" if results["baidu"] else "not_indexed",
            "toutiao_status": "indexed" if results["toutiao"] else "not_indexed",
            "sogou_status": "indexed" if results["sogou"] else "not_indexed",
            "so360_status": "indexed" if results["so360"] else "not_indexed",
            "bing_status": "indexed" if results["bing"] else "not_indexed",
            "baidu_checked_at": datetime.now() if results["baidu"] else None,
            "toutiao_checked_at": datetime.now() if results["toutiao"] else None,
            "sogou_checked_at": datetime.now() if results["sogou"] else None,
            "so360_checked_at": datetime.now() if results["so360"] else None,
            "bing_checked_at": datetime.now() if results["bing"] else None,
        }
        
        # 插入或更新收录结果
        existing = await self.db.execute(
            select(IndexResult).where(IndexResult.url == url)
        )
        
        if existing.scalar_one_or_none():
            await self.db.execute(
                update(IndexResult)
                .where(IndexResult.url == url)
                .values(**update_data)
            )
        else:
            new_result = IndexResult(**update_data)
            self.db.add(new_result)
        
        await self.db.commit()
        
        # 记录历史
        await self._record_history(url, results)
    
    async def _record_history(self, url: str, results: Dict[str, bool]):
        """记录检测历史"""
        today = datetime.now().date()
        
        # 检查是否已记录
        existing = await self.db.execute(
            select(IndexHistory)
            .where(IndexHistory.url == url, IndexHistory.check_date == today)
        )
        
        if existing.scalar_one_or_none():
            return
        
        # 计算总收录数
        total_indexed = sum(1 for v in results.values() if v)
        
        history = IndexHistory(
            url=url,
            check_date=today,
            baidu_status="indexed" if results["baidu"] else "not_indexed",
            toutiao_status="indexed" if results["toutiao"] else "not_indexed",
            sogou_status="indexed" if results["sogou"] else "not_indexed",
            so360_status="indexed" if results["so360"] else "not_indexed",
            bing_status="indexed" if results["bing"] else "not_indexed",
            total_indexed=total_indexed
        )
        
        self.db.add(history)
        await self.db.commit()
    
    async def check_all_pending(self):
        """检测所有待检测的 URL"""
        pending_urls = await self.get_pending_urls()
        
        for url in pending_urls:
            # TODO: 从 client_sites 表获取 client_id 和 site_type
            client_id = "default"
            site_type = "official"
            
            await self.check_url(url, client_id, site_type)
```

- [ ] **步骤 2：创建定时任务调度器**

```python
# index-monitor/app/services/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.database import async_session
from app.services.index_checker import IndexChecker
from app.core.config import settings

scheduler = AsyncIOScheduler()

async def scheduled_index_check():
    """定时收录检测任务"""
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()

def start_scheduler():
    """启动调度器"""
    # 从 system_config 表读取配置
    # 默认每天凌晨 2:00 执行
    scheduler.add_job(
        scheduled_index_check,
        CronTrigger(hour=2, minute=0),
        id="index_check",
        replace_existing=True
    )
    
    scheduler.start()

def stop_scheduler():
    """停止调度器"""
    scheduler.shutdown()
```

- [ ] **步骤 3：在 main.py 中集成调度器**

```python
# index-monitor/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.services.scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时启动调度器
    start_scheduler()
    yield
    # 关闭时停止调度器
    stop_scheduler()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan
)
```

- [ ] **步骤 4：编写调度器测试**

```python
# index-monitor/tests/test_scheduler.py
import pytest
from app.services.index_checker import IndexChecker
from app.core.database import async_session

@pytest.mark.asyncio
async def test_get_pending_urls():
    async with async_session() as db:
        checker = IndexChecker(db)
        urls = await checker.get_pending_urls()
        assert isinstance(urls, list)

@pytest.mark.asyncio
async def test_check_url():
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_url(
            url="https://www.example.com",
            client_id="test_client",
            site_type="official"
        )
        # 验证数据库已更新
```

- [ ] **步骤 5：运行测试**

```bash
pytest tests/test_scheduler.py -v
```

预期输出：`PASSED`

- [ ] **步骤 6：Commit**

```bash
git add index-monitor/app/services/
git commit -m "feat: 实现收录检测定时任务调度器"
```

**验收标准：**
- 定时任务能正确触发
- 收录检测结果正确写入数据库
- 历史记录正确记录
- 测试通过

---

## 阶段三：Dashboard 开发（第 4-5 天）

### 任务 8：Vue 3 项目初始化

**文件：**
- 创建：`dashboard/package.json`
- 创建：`dashboard/vite.config.js`
- 创建：`dashboard/src/main.js`
- 创建：`dashboard/src/App.vue`
- 创建：`dashboard/Dockerfile`

- [ ] **步骤 1：创建 package.json**

```json
{
  "name": "geo-dashboard",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.2.5",
    "vuex": "^4.1.0",
    "element-plus": "^2.5.0",
    "axios": "^1.6.0",
    "echarts": "^5.4.3",
    "vue-echarts": "^6.6.0",
    "dayjs": "^1.11.10"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "vite": "^5.0.0"
  }
}
```

- [ ] **步骤 2：创建 vite.config.js**

```javascript
// dashboard/vite.config.js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 3000
  },
  resolve: {
    alias: {
      '@': '/src'
    }
  }
})
```

- [ ] **步骤 3：创建 main.js**

```javascript
// dashboard/src/main.js
import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import store from './store'

const app = createApp(App)

app.use(ElementPlus)
app.use(router)
app.use(store)

app.mount('#app')
```

- [ ] **步骤 4：创建 App.vue**

```vue
<!-- dashboard/src/App.vue -->
<template>
  <router-view />
</template>

<script setup>
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', '微软雅黑', Arial, sans-serif;
}
</style>
```

- [ ] **步骤 5：创建 Dockerfile**

```dockerfile
# dashboard/Dockerfile
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

- [ ] **步骤 6：创建 nginx.conf**

```nginx
# dashboard/nginx.conf
server {
    listen 80;
    server_name localhost;
    
    root /usr/share/nginx/html;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://index-monitor:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

- [ ] **步骤 7：安装依赖并验证**

```bash
cd dashboard
npm install
npm run dev
```

访问 http://localhost:3000 应看到空白页面

- [ ] **步骤 8：Commit**

```bash
git add dashboard/
git commit -m "feat: 初始化 Vue 3 Dashboard 项目"
```

**验收标准：**
- Vue 3 项目初始化成功
- 开发服务器启动正常
- 依赖安装完成

---

### 任务 9：路由和状态管理

**文件：**
- 创建：`dashboard/src/router/index.js`
- 创建：`dashboard/src/store/index.js`
- 创建：`dashboard/src/api/index.js`

- [ ] **步骤 1：创建路由配置**

```javascript
// dashboard/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Dashboard from '../views/Dashboard.vue'
import Articles from '../views/Articles.vue'
import Settings from '../views/Settings.vue'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: Login
  },
  {
    path: '/',
    name: 'Dashboard',
    component: Dashboard,
    meta: { requiresAuth: true }
  },
  {
    path: '/articles',
    name: 'Articles',
    component: Articles,
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: Settings,
    meta: { requiresAuth: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  
  if (to.meta.requiresAuth && !token) {
    next('/login')
  } else {
    next()
  }
})

export default router
```

- [ ] **步骤 2：创建 Vuex 状态管理**

```javascript
// dashboard/src/store/index.js
import { createStore } from 'vuex'
import axios from 'axios'

export default createStore({
  state: {
    user: null,
    token: localStorage.getItem('token') || null,
    articles: [],
    indexStats: {
      total: 0,
      indexed: 0,
      rate: 0
    },
    citationStats: {
      total: 0,
      cited: 0,
      rate: 0
    }
  },
  
  mutations: {
    SET_USER(state, user) {
      state.user = user
    },
    SET_TOKEN(state, token) {
      state.token = token
      if (token) {
        localStorage.setItem('token', token)
        axios.defaults.headers.common['Authorization'] = `Bearer ${token}`
      } else {
        localStorage.removeItem('token')
        delete axios.defaults.headers.common['Authorization']
      }
    },
    SET_ARTICLES(state, articles) {
      state.articles = articles
    },
    SET_INDEX_STATS(state, stats) {
      state.indexStats = stats
    },
    SET_CITATION_STATS(state, stats) {
      state.citationStats = stats
    }
  },
  
  actions: {
    async login({ commit }, credentials) {
      const response = await axios.post('/api/v1/auth/login', credentials)
      commit('SET_TOKEN', response.data.access_token)
      commit('SET_USER', response.data.user)
      return response.data
    },
    
    async logout({ commit }) {
      commit('SET_TOKEN', null)
      commit('SET_USER', null)
    },
    
    async fetchArticles({ commit }) {
      const response = await axios.get('/api/v1/articles')
      commit('SET_ARTICLES', response.data)
    },
    
    async fetchIndexStats({ commit }) {
      const response = await axios.get('/api/v1/stats/index')
      commit('SET_INDEX_STATS', response.data)
    },
    
    async fetchCitationStats({ commit }) {
      const response = await axios.get('/api/v1/stats/citation')
      commit('SET_CITATION_STATS', response.data)
    }
  },
  
  getters: {
    isAuthenticated: state => !!state.token,
    getUser: state => state.user
  }
})
```

- [ ] **步骤 3：创建 API 调用模块**

```javascript
// dashboard/src/api/index.js
import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  response => response,
  error => {
    if (error.response.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
```

- [ ] **步骤 4：Commit**

```bash
git add dashboard/src/router/ dashboard/src/store/ dashboard/src/api/
git commit -m "feat: 配置 Vue Router 和 Vuex 状态管理"
```

**验收标准：**
- 路由配置正确
- 状态管理初始化完成
- API 模块配置正确

---

### 任务 10：登录页面

**文件：**
- 创建：`dashboard/src/views/Login.vue`

- [ ] **步骤 1：创建登录页面**

```vue
<!-- dashboard/src/views/Login.vue -->
<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header>
        <h2>GEO 监测系统</h2>
      </template>
      
      <el-form :model="form" :rules="rules" ref="formRef">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            prefix-icon="User"
          />
        </el-form-item>
        
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            @click="handleLogin"
            style="width: 100%"
          >
            登录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import { ElMessage } from 'element-plus'

const router = useRouter()
const store = useStore()
const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' }
  ]
}

const handleLogin = async () => {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    
    loading.value = true
    try {
      await store.dispatch('login', form)
      ElMessage.success('登录成功')
      router.push('/')
    } catch (error) {
      ElMessage.error('登录失败：' + (error.response?.data?.detail || '未知错误'))
    } finally {
      loading.value = false
    }
  })
}
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
  width: 400px;
}

h2 {
  text-align: center;
  color: #333;
}
</style>
```

- [ ] **步骤 2：Commit**

```bash
git add dashboard/src/views/Login.vue
git commit -m "feat: 实现用户登录页面"
```

**验收标准：**
- 登录页面渲染正常
- 表单验证生效
- 登录成功后跳转

---

### 任务 11：Dashboard 主页面

**文件：**
- 创建：`dashboard/src/views/Dashboard.vue`
- 创建：`dashboard/src/components/IndexChart.vue`
- 创建：`dashboard/src/components/CitationChart.vue`

- [ ] **步骤 1：创建 Dashboard 主页面**

```vue
<!-- dashboard/src/views/Dashboard.vue -->
<template>
  <div class="dashboard-container">
    <el-container>
      <el-header>
        <div class="header-content">
          <h1>GEO 监测仪表盘</h1>
          <el-button type="danger" @click="handleLogout">退出登录</el-button>
        </div>
      </el-header>
      
      <el-main>
        <!-- 统计卡片 -->
        <el-row :gutter="20" class="stats-row">
          <el-col :span="6">
            <el-card class="stat-card">
              <div class="stat-value">{{ indexStats.total }}</div>
              <div class="stat-label">总文章数</div>
            </el-card>
          </el-col>
          
          <el-col :span="6">
            <el-card class="stat-card">
              <div class="stat-value">{{ indexStats.indexed }}</div>
              <div class="stat-label">已收录数</div>
            </el-card>
          </el-col>
          
          <el-col :span="6">
            <el-card class="stat-card">
              <div class="stat-value">{{ (indexStats.rate * 100).toFixed(1) }}%</div>
              <div class="stat-label">收录率</div>
            </el-card>
          </el-col>
          
          <el-col :span="6">
            <el-card class="stat-card">
              <div class="stat-value">{{ citationStats.cited }}</div>
              <div class="stat-label">AI 采信数</div>
            </el-card>
          </el-col>
        </el-row>
        
        <!-- 图表区域 -->
        <el-row :gutter="20">
          <el-col :span="12">
            <el-card>
              <template #header>
                <span>收录趋势</span>
              </template>
              <IndexChart />
            </el-card>
          </el-col>
          
          <el-col :span="12">
            <el-card>
              <template #header>
                <span>搜索引擎分布</span>
              </template>
              <CitationChart />
            </el-card>
          </el-col>
        </el-row>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useStore } from 'vuex'
import IndexChart from '../components/IndexChart.vue'
import CitationChart from '../components/CitationChart.vue'

const router = useRouter()
const store = useStore()

const indexStats = computed(() => store.state.indexStats)
const citationStats = computed(() => store.state.citationStats)

onMounted(async () => {
  await store.dispatch('fetchIndexStats')
  await store.dispatch('fetchCitationStats')
})

const handleLogout = () => {
  store.dispatch('logout')
  router.push('/login')
}
</script>

<style scoped>
.dashboard-container {
  min-height: 100vh;
  background: #f5f7fa;
}

.el-header {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
}

h1 {
  font-size: 24px;
  color: #333;
}

.stats-row {
  margin-bottom: 20px;
}

.stat-card {
  text-align: center;
}

.stat-value {
  font-size: 32px;
  font-weight: bold;
  color: #409eff;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 14px;
  color: #999;
}
</style>
```

- [ ] **步骤 2：创建收录趋势图组件**

```vue
<!-- dashboard/src/components/IndexChart.vue -->
<template>
  <div ref="chartRef" style="height: 300px;"></div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import * as echarts from 'echarts'

const chartRef = ref(null)

onMounted(() => {
  const chart = echarts.init(chartRef.value)
  
  const option = {
    tooltip: {
      trigger: 'axis'
    },
    xAxis: {
      type: 'category',
      data: ['7天前', '6天前', '5天前', '4天前', '3天前', '2天前', '昨天']
    },
    yAxis: {
      type: 'value'
    },
    series: [
      {
        name: '收录数',
        type: 'line',
        data: [85, 88, 90, 92, 94, 95, 96],
        smooth: true,
        itemStyle: {
          color: '#409eff'
        }
      }
    ]
  }
  
  chart.setOption(option)
})
</script>
```

- [ ] **步骤 3：创建搜索引擎分布图组件**

```vue
<!-- dashboard/src/components/CitationChart.vue -->
<template>
  <div ref="chartRef" style="height: 300px;"></div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import * as echarts from 'echarts'

const chartRef = ref(null)

onMounted(() => {
  const chart = echarts.init(chartRef.value)
  
  const option = {
    tooltip: {
      trigger: 'item'
    },
    series: [
      {
        name: '搜索引擎',
        type: 'pie',
        radius: ['40%', '70%'],
        data: [
          { value: 96, name: '百度' },
          { value: 88, name: '头条' },
          { value: 85, name: '搜狗' },
          { value: 90, name: '360' },
          { value: 92, name: '必应' }
        ],
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowOffsetX: 0,
            shadowColor: 'rgba(0, 0, 0, 0.5)'
          }
        }
      }
    ]
  }
  
  chart.setOption(option)
})
</script>
```

- [ ] **步骤 4：Commit**

```bash
git add dashboard/src/views/Dashboard.vue dashboard/src/components/
git commit -m "feat: 实现 Dashboard 主页面和图表组件"
```

**验收标准：**
- Dashboard 页面渲染正常
- 统计卡片显示正确
- 图表渲染正常

---

## 阶段四：集成与部署（第 6 天）

### 任务 12：Docker Compose 编排

**文件：**
- 创建：`deploy/docker-compose.yml`

- [ ] **步骤 1：创建主 docker-compose 文件**

```yaml
# deploy/docker-compose.yml
version: '3.8'

services:
  # 数据库服务
  postgres:
    image: postgres:15-alpine
    container_name: geo-postgres
    restart: always
    environment:
      POSTGRES_DB: geo_monitoring
      POSTGRES_USER: geo_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    ports:
      - "127.0.0.1:5432:5432"
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '0.5'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U geo_user -d geo_monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: geo-redis
    restart: always
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.25'

  # 收录检测服务
  index-monitor:
    build: ../index-monitor
    container_name: geo-index-monitor
    restart: always
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: 5432
      POSTGRES_DB: geo_monitoring
      POSTGRES_USER: geo_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_PASSWORD: ${REDIS_PASSWORD}
      SECRET_KEY: ${JWT_SECRET}
    ports:
      - "127.0.0.1:8090:8090"
    depends_on:
      postgres:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: '0.5'

  # Dashboard 前端
  dashboard:
    build: ../dashboard
    container_name: geo-dashboard
    restart: always
    ports:
      - "127.0.0.1:3000:80"
    depends_on:
      - index-monitor
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.25'

  # Nginx 反向代理
  nginx:
    image: nginx:alpine
    container_name: geo-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/conf.d:/etc/nginx/conf.d
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - dashboard
      - index-monitor
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.25'

volumes:
  postgres_data:
  redis_data:
```

- [ ] **步骤 2：创建 Nginx 配置**

```nginx
# deploy/nginx/nginx.conf
worker_processes 2;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    
    sendfile on;
    keepalive_timeout 65;
    
    # 限流配置
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    
    # 日志格式
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent"';
    
    access_log /var/log/nginx/access.log main;
    error_log /var/log/nginx/error.log warn;
    
    include /etc/nginx/conf.d/*.conf;
}
```

```nginx
# deploy/nginx/conf.d/default.conf
server {
    listen 80;
    server_name 124.220.33.188;
    
    # 强制 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name 124.220.33.188;
    
    # SSL 证书（需要自行配置）
    # ssl_certificate /etc/nginx/ssl/cert.pem;
    # ssl_certificate_key /etc/nginx/ssl/key.pem;
    
    # Dashboard 前端
    location / {
        proxy_pass http://dashboard:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    
    # 收录检测服务 API
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
        
        proxy_pass http://index-monitor:8090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **步骤 3：启动所有服务**

```bash
cd /opt/geo-monitoring/deploy
docker compose up -d
docker compose ps
```

**验收标准：**
- 所有容器运行正常
- Nginx 反代配置正确
- 服务间通信正常

---

### 任务 13：端到端测试

- [ ] **步骤 1：测试完整流程**

```bash
# 1. 测试健康检查
curl http://124.220.33.188/api/v1/health

# 2. 测试登录
curl -X POST http://124.220.33.188/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}'

# 3. 测试 Dashboard 访问
curl http://124.220.33.188/
```

- [ ] **步骤 2：测试收录检测**

```bash
# 手动触发收录检测
curl -X POST http://124.220.33.188/api/v1/index/check \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com"}'
```

- [ ] **步骤 3：验证数据库**

```bash
docker exec -it geo-postgres psql -U geo_user -d geo_monitoring

# 查看收录结果
SELECT * FROM index_results LIMIT 5;

# 查看历史记录
SELECT * FROM index_history LIMIT 5;
```

- [ ] **步骤 4：Commit**

```bash
git add .
git commit -m "feat: 完成系统集成和端到端测试"
```

**验收标准：**
- 完整流程测试通过
- 数据库数据正确
- 无报错日志

---

## 部署检查清单

### 部署前检查

- [ ] 服务器环境初始化完成
- [ ] Docker 和 Docker Compose 版本正确
- [ ] 防火墙配置正确（22/80/443）
- [ ] `.env` 文件配置完成
- [ ] SSL 证书准备就绪（如需 HTTPS）

### 部署步骤

```bash
# 1. 上传项目文件
rsync -avz "/home/tishensnoopy/GEO FLOW+LUMORA CITE/" ubuntu@124.220.33.188:/opt/geo-monitoring/

# 2. SSH 登录服务器
ssh ubuntu@124.220.33.188

# 3. 进入项目目录
cd /opt/geo-monitoring/deploy

# 4. 启动所有服务
docker compose up -d

# 5. 查看服务状态
docker compose ps

# 6. 查看日志
docker compose logs -f
```

### 部署后验证

- [ ] 所有容器运行正常
- [ ] Dashboard 可访问
- [ ] API 接口正常
- [ ] 数据库连接正常
- [ ] 定时任务正常执行

---

## 后续优化

1. **SSL 证书配置**：使用 Let's Encrypt 配置免费 SSL 证书
2. **监控告警**：集成 Prometheus + Grafana 监控系统
3. **日志收集**：集成 ELK Stack 日志收集系统
4. **自动备份**：配置数据库自动备份脚本
5. **性能优化**：根据实际负载调整资源限制

---

**计划完成！**
