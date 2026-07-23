# GEO 内容分发 + 收录 AI 监测系统 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建一个完整的 GEO 内容分发与收录监测系统，实现文章生成、推送、收录检测、AI 采信检测和客户 Dashboard 展示的全链路闭环。

**架构：** 基于 GEOFlow（内容生成）+ 自研收录检测服务（Python）+ lumora-cite（AI 采信检测）+ Vue 3 Dashboard 的四层架构，使用 Docker Compose 编排，PostgreSQL 统一存储，Nginx 反向代理。

**技术栈：**
- 后端：Laravel 11（GEOFlow）、Python 3.11 + FastAPI（检测服务）、Vue 3 + Element Plus（Dashboard）
- 数据库：PostgreSQL 15 + Redis 7
- 部署：Docker Compose + Nginx
- 服务器：Ubuntu 22.04 LTS（4核4G40GB）

**执行原则：** 所有开发和本地测试在本地完成，全部通过后才能上云部署。

---

## 安全配置

### 凭据管理

**禁止在代码库中存储明文密码！**

创建 `.env` 文件（必须加入 `.gitignore`）：

```bash
# 本地开发环境
POSTGRES_PASSWORD=GeoLocal2026
REDIS_PASSWORD=RedisLocal2026
JWT_SECRET=local-jwt-secret-key-for-testing
DEBUG=true

# 生产环境（仅部署时使用，不提交）
PROD_SERVER_IP=124.220.33.188
PROD_SERVER_USER=ubuntu
PROD_POSTGRES_PASSWORD=Geo@2026Secure
PROD_REDIS_PASSWORD=Redis@2026Secure
PROD_JWT_SECRET=production-jwt-secret-change-me
```

---

## 文件结构

```
/home/tishensnoopy/GEO FLOW+LUMORA CITE/
├── GEOFlow-main/                          # 内容生成系统（已有）
├── lumora-cite-main/                      # AI 采信检测（已有）
├── index-monitor/                         # 收录检测服务（新建）
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                        # FastAPI 入口
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py                  # API 路由
│   │   │   └── deps.py                    # 依赖注入
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py                  # 配置管理
│   │   │   ├── security.py                # 安全认证
│   │   │   └── database.py                # 数据库连接
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                    # SQLAlchemy Base
│   │   │   ├── article.py                 # 文章模型
│   │   │   ├── index_result.py            # 收录结果模型
│   │   │   ├── citation_result.py         # AI 采信结果模型
│   │   │   └── client.py                  # 客户模型
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── index_checker.py           # 收录检测逻辑
│   │   │   ├── spider.py                  # 爬虫服务
│   │   │   └── scheduler.py               # 定时任务
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── http_client.py             # HTTP 客户端
│   │       └── logger.py                  # 日志工具
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py                    # pytest 配置
│   │   ├── test_api.py
│   │   ├── test_spider.py
│   │   ├── test_scheduler.py
│   │   └── test_models.py
│   ├── requirements.txt
│   ├── Dockerfile
│   └── docker-compose.yml                 # 本地开发用
├── dashboard/                             # 客户 Dashboard（新建）
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── router/index.js
│   │   ├── store/index.js
│   │   ├── views/
│   │   │   ├── Login.vue
│   │   │   ├── Dashboard.vue
│   │   │   ├── Articles.vue
│   │   │   └── Settings.vue
│   │   ├── components/
│   │   │   ├── IndexChart.vue
│   │   │   ├── CitationChart.vue
│   │   │   ├── ArticleCard.vue
│   │   │   └── ArticleModal.vue
│   │   ├── api/index.js
│   │   └── utils/auth.js
│   ├── public/index.html
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── deploy/                                # 生产部署配置（新建）
│   ├── docker-compose.prod.yml            # 生产编排文件
│   ├── nginx/
│   │   ├── nginx.conf
│   │   └── conf.d/
│   │       └── default.conf
│   └── scripts/
│       ├── init-server.sh                 # 服务器初始化
│       ├── init-db.sh                     # 数据库初始化
│       ├── backup.sh                      # 备份脚本
│       └── deploy.sh                      # 部署脚本
├── docker-compose.local.yml               # 本地开发编排
├── .env                                   # 环境变量（不提交）
├── .env.example                           # 环境变量模板
└── docs/
```

---

## 阶段一：本地开发（第 1-5 天）

> 所有编码工作在本地完成，使用 Docker Compose 运行本地依赖服务。

### 任务 1：本地 Docker 环境准备

**文件：**
- 创建：`docker-compose.local.yml`
- 创建：`.env.example`
- 修改：`.gitignore`

- [ ] **步骤 1：将敏感文件加入 .gitignore**

```gitignore
# .gitignore 追加
.env
*.env.local
deploy/ssl/
```

- [ ] **步骤 2：创建环境变量模板**

```bash
# .env.example
POSTGRES_PASSWORD=change_me
REDIS_PASSWORD=change_me
JWT_SECRET=change_me
DEBUG=true
```

- [ ] **步骤 3：创建本地 docker-compose 配置**

```yaml
# docker-compose.local.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: geo-postgres-local
    restart: unless-stopped
    environment:
      POSTGRES_DB: geo_monitoring
      POSTGRES_USER: geo_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-GeoLocal2026}
    volumes:
      - postgres_data_local:/var/lib/postgresql/data
      - ./deploy/scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U geo_user -d geo_monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: geo-redis-local
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD:-RedisLocal2026}
    volumes:
      - redis_data_local:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-RedisLocal2026}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data_local:
  redis_data_local:
```

- [ ] **步骤 4：创建数据库初始化脚本**

```bash
#!/bin/bash
# deploy/scripts/init-db.sh
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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

    CREATE TABLE IF NOT EXISTS system_config (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        config_key VARCHAR(128) UNIQUE NOT NULL,
        config_value TEXT NOT NULL,
        config_type VARCHAR(32) NOT NULL,
        description TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    INSERT INTO system_config (config_key, config_value, config_type, description) VALUES
    ('index_scan_frequency', '1', 'number', '收录检测频率（天/次）'),
    ('index_scan_time', '02:00', 'string', '收录检测执行时间'),
    ('citation_scan_frequency', '7', 'number', 'AI 采信检测频率（天/次）'),
    ('citation_scan_time', '03:00', 'string', 'AI 采信检测执行时间'),
    ('citation_sample_size', '20', 'number', 'AI 采信检测抽样数量'),
    ('spider_concurrent', '3', 'number', '爬虫并发数'),
    ('spider_interval_min', '2', 'number', '爬虫最小间隔（秒）'),
    ('spider_interval_max', '5', 'number', '爬虫最大间隔（秒）')
    ON CONFLICT (config_key) DO NOTHING;
EOSQL
```

- [ ] **步骤 5：启动本地依赖服务**

```bash
docker compose -f docker-compose.local.yml up -d
docker compose -f docker-compose.local.yml ps
```

预期输出：postgres 和 redis 两个容器状态为 `healthy`

- [ ] **步骤 6：验证数据库初始化**

```bash
docker exec -it geo-postgres-local psql -U geo_user -d geo_monitoring -c "\dt"
```

预期输出：显示 7 张表（article_distributions, index_results, index_history, citation_results, clients, client_sites, system_config）

- [ ] **步骤 7：Commit**

```bash
git add docker-compose.local.yml .env.example .gitignore deploy/scripts/init-db.sh
git commit -m "feat: 本地 Docker 环境和数据库初始化脚本"
```

**验收标准：**
- PostgreSQL 容器运行正常，端口 5432 可访问
- Redis 容器运行正常，端口 6379 可访问
- 7 张表创建成功
- system_config 表有 8 条默认配置

---

### 任务 2：收录检测服务 - FastAPI 基础框架

**文件：**
- 创建：`index-monitor/requirements.txt`
- 创建：`index-monitor/app/__init__.py`
- 创建：`index-monitor/app/main.py`
- 创建：`index-monitor/app/core/__init__.py`
- 创建：`index-monitor/app/core/config.py`
- 创建：`index-monitor/app/core/database.py`
- 创建：`index-monitor/app/models/__init__.py`
- 创建：`index-monitor/app/models/base.py`
- 创建：`index-monitor/Dockerfile`

- [ ] **步骤 1：创建 requirements.txt**

```txt
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
pytest==7.4.4
pytest-asyncio==0.23.3
```

- [ ] **步骤 2：创建配置管理模块**

```python
# index-monitor/app/core/config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "Index Monitor Service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "geo_monitoring"
    POSTGRES_USER: str = "geo_user"
    POSTGRES_PASSWORD: str = "GeoLocal2026"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "RedisLocal2026"

    SECRET_KEY: str = "local-jwt-secret-key-for-testing"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    SPIDER_CONCURRENT: int = 3
    SPIDER_INTERVAL_MIN: int = 2
    SPIDER_INTERVAL_MAX: int = 5

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

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

engine = create_async_engine(DATABASE_URL, echo=settings.DEBUG)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
```

- [ ] **步骤 4：创建 SQLAlchemy Base**

```python
# index-monitor/app/models/base.py
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

- [ ] **步骤 5：创建 FastAPI 主入口**

```python
# index-monitor/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
```

- [ ] **步骤 6：创建 Dockerfile**

```dockerfile
# index-monitor/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
```

- [ ] **步骤 7：本地安装依赖并验证启动**

```bash
cd index-monitor
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

- [ ] **步骤 8：验证健康检查**

```bash
curl http://localhost:8090/health
```

预期输出：`{"status": "healthy", "version": "1.0.0"}`

- [ ] **步骤 9：Commit**

```bash
git add index-monitor/
git commit -m "feat: 收录检测服务 FastAPI 基础框架"
```

**验收标准：**
- FastAPI 应用启动成功
- 健康检查接口返回 200
- 数据库连接正常

---

### 任务 3：收录检测服务 - 数据模型

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
from app.models.base import Base
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
from app.models.base import Base
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
    baidu_status = Column(String(32), default="pending")
    toutiao_status = Column(String(32), default="pending")
    sogou_status = Column(String(32), default="pending")
    so360_status = Column(String(32), default="pending")
    bing_status = Column(String(32), default="pending")
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
from app.models.base import Base
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
from app.models.base import Base
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

- [ ] **步骤 5：Commit**

```bash
git add index-monitor/app/models/
git commit -m "feat: 收录检测服务数据模型定义"
```

**验收标准：**
- 所有模型定义正确
- 与数据库表结构一一对应

---

### 任务 4：收录检测服务 - 爬虫与 API

**文件：**
- 创建：`index-monitor/app/utils/__init__.py`
- 创建：`index-monitor/app/utils/http_client.py`
- 创建：`index-monitor/app/services/__init__.py`
- 创建：`index-monitor/app/services/spider.py`
- 创建：`index-monitor/app/services/index_checker.py`
- 创建：`index-monitor/app/services/scheduler.py`
- 创建：`index-monitor/app/api/__init__.py`
- 创建：`index-monitor/app/api/routes.py`
- 创建：`index-monitor/app/api/deps.py`
- 创建：`index-monitor/app/core/security.py`

- [ ] **步骤 1：创建 HTTP 客户端**

```python
# index-monitor/app/utils/http_client.py
import httpx
import random
import asyncio
from typing import Optional, Dict
from app.core.config import settings

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

class HttpClient:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    def get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def get(self, url: str, headers: Optional[Dict] = None) -> httpx.Response:
        if headers is None:
            headers = {}
        headers["User-Agent"] = self.get_random_ua()
        await self._random_delay()
        return await self.client.get(url, headers=headers)

    async def _random_delay(self):
        delay = random.randint(settings.SPIDER_INTERVAL_MIN, settings.SPIDER_INTERVAL_MAX)
        await asyncio.sleep(delay)

    async def close(self):
        await self.client.aclose()

http_client = HttpClient()
```

- [ ] **步骤 2：创建爬虫服务**

```python
# index-monitor/app/services/spider.py
import asyncio
from typing import Dict
from bs4 import BeautifulSoup
from app.utils.http_client import http_client
from app.core.config import settings

class IndexSpider:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.SPIDER_CONCURRENT)

    async def check_baidu(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.baidu.com/s?wd=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='result')) > 0
            except Exception as e:
                print(f"百度检测失败: {url}, 错误: {e}")
                return False

    async def check_toutiao(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://so.toutiao.com/search?keyword=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='result')) > 0
            except Exception as e:
                print(f"头条检测失败: {url}, 错误: {e}")
                return False

    async def check_sogou(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.sogou.com/web?query=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('div', class_='rb')) > 0
            except Exception as e:
                print(f"搜狗检测失败: {url}, 错误: {e}")
                return False

    async def check_so360(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.so.com/s?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='res-list')) > 0
            except Exception as e:
                print(f"360检测失败: {url}, 错误: {e}")
                return False

    async def check_bing(self, url: str) -> bool:
        async with self.semaphore:
            try:
                response = await http_client.get(f"https://www.bing.com/search?q=site:{url}")
                soup = BeautifulSoup(response.text, 'lxml')
                return len(soup.find_all('li', class_='b_algo')) > 0
            except Exception as e:
                print(f"必应检测失败: {url}, 错误: {e}")
                return False

    async def check_all_engines(self, url: str) -> Dict[str, bool]:
        results = await asyncio.gather(
            self.check_baidu(url),
            self.check_toutiao(url),
            self.check_sogou(url),
            self.check_so360(url),
            self.check_bing(url)
        )
        return {
            "baidu": results[0],
            "toutiao": results[1],
            "sogou": results[2],
            "so360": results[3],
            "bing": results[4]
        }

spider = IndexSpider()
```

- [ ] **步骤 3：创建收录检测服务**

```python
# index-monitor/app/services/index_checker.py
from datetime import datetime
from typing import List, Dict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.article import ArticleDistribution
from app.models.index_result import IndexResult, IndexHistory
from app.services.spider import spider

class IndexChecker:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.spider = spider

    async def get_pending_urls(self) -> List[str]:
        result = await self.db.execute(
            select(ArticleDistribution.remote_url).where(ArticleDistribution.status == "synced")
        )
        distributed_urls = {row[0] for row in result.fetchall()}

        result = await self.db.execute(select(IndexResult.url))
        checked_urls = {row[0] for row in result.fetchall()}

        return list(distributed_urls - checked_urls)

    async def check_url(self, url: str, client_id: str, site_type: str):
        results = await self.spider.check_all_engines(url)
        now = datetime.now()

        update_data = {
            "url": url,
            "client_id": client_id,
            "site_type": site_type,
            "baidu_status": "indexed" if results["baidu"] else "not_indexed",
            "toutiao_status": "indexed" if results["toutiao"] else "not_indexed",
            "sogou_status": "indexed" if results["sogou"] else "not_indexed",
            "so360_status": "indexed" if results["so360"] else "not_indexed",
            "bing_status": "indexed" if results["bing"] else "not_indexed",
            "baidu_checked_at": now if results["baidu"] else None,
            "toutiao_checked_at": now if results["toutiao"] else None,
            "sogou_checked_at": now if results["sogou"] else None,
            "so360_checked_at": now if results["so360"] else None,
            "bing_checked_at": now if results["bing"] else None,
        }

        existing = await self.db.execute(select(IndexResult).where(IndexResult.url == url))
        if existing.scalar_one_or_none():
            await self.db.execute(update(IndexResult).where(IndexResult.url == url).values(**update_data))
        else:
            self.db.add(IndexResult(**update_data))

        await self.db.commit()
        await self._record_history(url, results)

    async def _record_history(self, url: str, results: Dict[str, bool]):
        today = datetime.now().date()
        existing = await self.db.execute(
            select(IndexHistory).where(IndexHistory.url == url, IndexHistory.check_date == today)
        )
        if existing.scalar_one_or_none():
            return

        total_indexed = sum(1 for v in results.values() if v)
        self.db.add(IndexHistory(
            url=url, check_date=today,
            baidu_status="indexed" if results["baidu"] else "not_indexed",
            toutiao_status="indexed" if results["toutiao"] else "not_indexed",
            sogou_status="indexed" if results["sogou"] else "not_indexed",
            so360_status="indexed" if results["so360"] else "not_indexed",
            bing_status="indexed" if results["bing"] else "not_indexed",
            total_indexed=total_indexed
        ))
        await self.db.commit()

    async def check_all_pending(self):
        pending_urls = await self.get_pending_urls()
        for url in pending_urls:
            await self.check_url(url, "default", "official")
```

- [ ] **步骤 4：创建定时任务调度器**

```python
# index-monitor/app/services/scheduler.py
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.database import async_session
from app.services.index_checker import IndexChecker

scheduler = AsyncIOScheduler()

async def scheduled_index_check():
    async with async_session() as db:
        checker = IndexChecker(db)
        await checker.check_all_pending()

def start_scheduler():
    scheduler.add_job(
        scheduled_index_check,
        CronTrigger(hour=2, minute=0),
        id="index_check",
        replace_existing=True
    )
    scheduler.start()

def stop_scheduler():
    scheduler.shutdown()
```

- [ ] **步骤 5：创建安全认证模块**

```python
# index-monitor/app/core/security.py
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"])

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)
```

- [ ] **步骤 6：创建 API 路由**

```python
# index-monitor/app/api/routes.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import create_access_token, verify_password, hash_password
from app.models.client import Client
from app.models.index_result import IndexResult, IndexHistory
from app.models.citation_result import CitationResult
from app.services.index_checker import IndexChecker

router = APIRouter()

@router.post("/auth/login")
async def login(username: str, password: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Client).where(Client.username == username))
    client = result.scalar_one_or_none()
    if not client or not verify_password(password, client.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": client.client_id})
    return {"access_token": token, "token_type": "bearer"}

@router.get("/stats/index")
async def get_index_stats(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IndexResult).where(IndexResult.client_id == client_id))
    articles = result.scalars().all()
    total = len(articles)
    indexed = sum(1 for a in articles if any([
        a.baidu_status == "indexed", a.toutiao_status == "indexed",
        a.sogou_status == "indexed", a.so360_status == "indexed",
        a.bing_status == "indexed"
    ]))
    return {"total": total, "indexed": indexed, "rate": indexed / total if total > 0 else 0}

@router.get("/stats/citation")
async def get_citation_stats(client_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CitationResult).where(CitationResult.url.in_(
            select(IndexResult.url).where(IndexResult.client_id == client_id)
        ))
    )
    citations = result.scalars().all()
    return {"total": len(citations), "cited": sum(1 for c in citations if c.hit_type != "none")}

@router.post("/index/check")
async def trigger_index_check(db: AsyncSession = Depends(get_db)):
    checker = IndexChecker(db)
    await checker.check_all_pending()
    return {"message": "收录检测任务已完成"}
```

- [ ] **步骤 7：更新 main.py 集成路由和调度器**

```python
# index-monitor/app/main.py（完整版本）
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import router
from app.services.scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": settings.APP_VERSION}
```

- [ ] **步骤 8：验证 API 启动**

```bash
cd index-monitor
uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
curl http://localhost:8090/health
```

预期输出：`{"status": "healthy", "version": "1.0.0"}`

- [ ] **步骤 9：Commit**

```bash
git add index-monitor/
git commit -m "feat: 收录检测服务爬虫、API 路由和定时任务"
```

**验收标准：**
- 爬虫能正确检测各搜索引擎收录状态
- API 路由注册成功
- 定时任务调度器启动正常
- 健康检查通过

---

### 任务 5：Dashboard 前端开发

**文件：**
- 创建：`dashboard/package.json`
- 创建：`dashboard/vite.config.js`
- 创建：`dashboard/index.html`
- 创建：`dashboard/src/main.js`
- 创建：`dashboard/src/App.vue`
- 创建：`dashboard/src/router/index.js`
- 创建：`dashboard/src/store/index.js`
- 创建：`dashboard/src/api/index.js`
- 创建：`dashboard/src/views/Login.vue`
- 创建：`dashboard/src/views/Dashboard.vue`
- 创建：`dashboard/src/views/Articles.vue`
- 创建：`dashboard/src/views/Settings.vue`
- 创建：`dashboard/src/components/IndexChart.vue`
- 创建：`dashboard/src/components/CitationChart.vue`
- 创建：`dashboard/src/components/ArticleModal.vue`

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
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { host: '0.0.0.0', port: 3000 },
  resolve: { alias: { '@': '/src' } }
})
```

- [ ] **步骤 3：创建入口文件 main.js 和 App.vue**

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

```vue
<!-- dashboard/src/App.vue -->
<template>
  <router-view />
</template>
```

- [ ] **步骤 4：创建路由配置**

```javascript
// dashboard/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/Login.vue') },
  { path: '/', name: 'Dashboard', component: () => import('../views/Dashboard.vue'), meta: { requiresAuth: true } },
  { path: '/articles', name: 'Articles', component: () => import('../views/Articles.vue'), meta: { requiresAuth: true } },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue'), meta: { requiresAuth: true } }
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.requiresAuth && !token) next('/login')
  else next()
})

export default router
```

- [ ] **步骤 5：创建状态管理和 API 模块**

```javascript
// dashboard/src/store/index.js
import { createStore } from 'vuex'
import api from '../api'

export default createStore({
  state: {
    user: null,
    token: localStorage.getItem('token') || null,
    indexStats: { total: 0, indexed: 0, rate: 0 },
    citationStats: { total: 0, cited: 0, rate: 0 }
  },
  mutations: {
    SET_TOKEN(state, token) {
      state.token = token
      if (token) localStorage.setItem('token', token)
      else localStorage.removeItem('token')
    },
    SET_INDEX_STATS(state, stats) { state.indexStats = stats },
    SET_CITATION_STATS(state, stats) { state.citationStats = stats }
  },
  actions: {
    async login({ commit }, credentials) {
      const res = await api.post('/auth/login', credentials)
      commit('SET_TOKEN', res.data.access_token)
      return res.data
    },
    async logout({ commit }) { commit('SET_TOKEN', null) },
    async fetchIndexStats({ commit }) {
      const res = await api.get('/stats/index')
      commit('SET_INDEX_STATS', res.data)
    },
    async fetchCitationStats({ commit }) {
      const res = await api.get('/stats/citation')
      commit('SET_CITATION_STATS', res.data)
    }
  },
  getters: {
    isAuthenticated: state => !!state.token
  }
})
```

```javascript
// dashboard/src/api/index.js
import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1', timeout: 30000 })

api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  res => res,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
```

- [ ] **步骤 6：创建 Login.vue 登录页**

```vue
<!-- dashboard/src/views/Login.vue -->
<template>
  <div class="login-container">
    <el-card class="login-card">
      <template #header><h2>GEO 监测系统</h2></template>
      <el-form :model="form" :rules="rules" ref="formRef">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" prefix-icon="Lock" @keyup.enter="handleLogin" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleLogin" style="width: 100%">登录</el-button>
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
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
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
.login-container { display: flex; justify-content: center; align-items: center; min-height: 100vh; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.login-card { width: 400px; }
h2 { text-align: center; color: #333; }
</style>
```

- [ ] **步骤 7：创建 Dashboard.vue 主页面**

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
        <el-row :gutter="20" class="stats-row">
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ indexStats.total }}</div><div class="stat-label">总文章数</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ indexStats.indexed }}</div><div class="stat-label">已收录数</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ (indexStats.rate * 100).toFixed(1) }}%</div><div class="stat-label">收录率</div></el-card></el-col>
          <el-col :span="6"><el-card class="stat-card"><div class="stat-value">{{ citationStats.cited }}</div><div class="stat-label">AI 采信数</div></el-card></el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="12"><el-card><template #header><span>收录趋势</span></template><IndexChart /></el-card></el-col>
          <el-col :span="12"><el-card><template #header><span>搜索引擎分布</span></template><CitationChart /></el-card></el-col>
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
.dashboard-container { min-height: 100vh; background: #f5f7fa; }
.el-header { background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
.header-content { display: flex; justify-content: space-between; align-items: center; height: 100%; }
h1 { font-size: 24px; color: #333; }
.stats-row { margin-bottom: 20px; }
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: bold; color: #409eff; margin-bottom: 8px; }
.stat-label { font-size: 14px; color: #999; }
</style>
```

- [ ] **步骤 8：创建图表组件**

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
  chart.setOption({
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['7天前', '6天前', '5天前', '4天前', '3天前', '2天前', '昨天'] },
    yAxis: { type: 'value' },
    series: [{ name: '收录数', type: 'line', data: [85, 88, 90, 92, 94, 95, 96], smooth: true, itemStyle: { color: '#409eff' } }]
  })
})
</script>
```

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
  chart.setOption({
    tooltip: { trigger: 'item' },
    series: [{
      name: '搜索引擎', type: 'pie', radius: ['40%', '70%'],
      data: [
        { value: 96, name: '百度' }, { value: 88, name: '头条' },
        { value: 85, name: '搜狗' }, { value: 90, name: '360' }, { value: 92, name: '必应' }
      ]
    }]
  })
})
</script>
```

- [ ] **步骤 9：创建 Articles.vue 和 Settings.vue 骨架页面**

```vue
<!-- dashboard/src/views/Articles.vue -->
<template>
  <div style="padding: 20px;">
    <h2>文章列表</h2>
    <el-table :data="articles" style="width: 100%">
      <el-table-column prop="title" label="文章标题" />
      <el-table-column prop="baidu_status" label="百度" />
      <el-table-column prop="toutiao_status" label="头条" />
      <el-table-column prop="checked_at" label="检测时间" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const articles = ref([])

onMounted(async () => {
  try {
    const res = await api.get('/articles')
    articles.value = res.data
  } catch (e) {
    console.error('加载文章失败', e)
  }
})
</script>
```

```vue
<!-- dashboard/src/views/Settings.vue -->
<template>
  <div style="padding: 20px;">
    <h2>系统设置</h2>
    <el-form :model="config" label-width="200px">
      <el-form-item label="收录检测频率（天/次）">
        <el-input-number v-model="config.index_scan_frequency" :min="1" :max="30" />
      </el-form-item>
      <el-form-item label="AI 采信检测频率（天/次）">
        <el-input-number v-model="config.citation_scan_frequency" :min="1" :max="30" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveConfig">保存配置</el-button>
        <el-button type="warning" @click="triggerScan('index')">立即收录扫描</el-button>
        <el-button type="warning" @click="triggerScan('citation')">立即 AI 采信扫描</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const config = ref({})

onMounted(async () => {
  try {
    const res = await api.get('/config')
    config.value = res.data
  } catch (e) {
    console.error('加载配置失败', e)
  }
})

const saveConfig = async () => {
  try {
    await api.put('/config', config.value)
    ElMessage.success('配置保存成功')
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

const triggerScan = async (type) => {
  try {
    await api.post(`/scan/trigger/${type}`)
    ElMessage.success('扫描任务已触发')
  } catch (e) {
    ElMessage.error('触发失败')
  }
}
</script>
```

- [ ] **步骤 10：创建 ArticleModal.vue 文章详情弹窗**

```vue
<!-- dashboard/src/components/ArticleModal.vue -->
<template>
  <el-dialog v-model="visible" :title="article.title || '文章详情'" width="70%">
    <el-descriptions :column="2" border>
      <el-descriptions-item label="发布时间">{{ article.created_at }}</el-descriptions-item>
      <el-descriptions-item label="URL">{{ article.url }}</el-descriptions-item>
      <el-descriptions-item label="百度收录">{{ article.baidu_status }}</el-descriptions-item>
      <el-descriptions-item label="头条收录">{{ article.toutiao_status }}</el-descriptions-item>
      <el-descriptions-item label="搜狗收录">{{ article.sogou_status }}</el-descriptions-item>
      <el-descriptions-item label="360收录">{{ article.so360_status }}</el-descriptions-item>
      <el-descriptions-item label="必应收录">{{ article.bing_status }}</el-descriptions-item>
      <el-descriptions-item label="AI 采信">{{ article.citation_status }}</el-descriptions-item>
    </el-descriptions>
    <el-divider>原文快照</el-divider>
    <div class="snapshot" v-html="article.content_snapshot"></div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" @click="viewOriginal">查看原文</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({ modelValue: Boolean, article: Object })
const emit = defineEmits(['update:modelValue'])
const visible = ref(props.modelValue)

watch(() => props.modelValue, (val) => { visible.value = val })
watch(visible, (val) => { emit('update:modelValue', val) })

const viewOriginal = () => {
  if (props.article.url) window.open(props.article.url, '_blank')
}
</script>

<style scoped>
.snapshot { max-height: 300px; overflow-y: auto; padding: 12px; background: #f9f9f9; border-radius: 4px; }
</style>
```

- [ ] **步骤 11：本地启动 Dashboard 验证**

```bash
cd dashboard
npm install
npm run dev
```

访问 http://localhost:3000 应看到登录页。

- [ ] **步骤 12：Commit**

```bash
git add dashboard/
git commit -m "feat: 完成 Dashboard 前端开发（登录、仪表盘、文章列表、设置）"
```

**验收标准：**
- Dashboard 页面渲染正常
- 登录表单验证生效
- 图表组件渲染正常
- 设置页可调整扫描频率、触发立即扫描

---

## 阶段二：本地集成测试（第 6-7 天）

> **核心原则：所有功能必须在本地跑通后才能上云。**

### 任务 6：本地全链路启动

- [ ] **步骤 1：启动本地完整环境**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
docker compose -f docker-compose.local.yml up -d --build

# 查看所有服务状态
docker compose -f docker-compose.local.yml ps
```

预期输出：所有服务状态为 `running` / `healthy`：
- geo-postgres-local (healthy)
- geo-redis-local (healthy)
- geo-index-monitor-local (running)
- geo-dashboard-local (running)

- [ ] **步骤 2：检查服务日志无报错**

```bash
# 收录检测服务日志
docker compose -f docker-compose.local.yml logs index-monitor

# Dashboard 日志
docker compose -f docker-compose.local.yml logs dashboard
```

**验收标准：**
- 4 个容器全部运行
- 无报错日志

---

### 任务 7：数据库层验证

- [ ] **步骤 1：验证表结构完整**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring -c "\dt"
```

预期输出 7 张表：
```
article_distributions, citation_results, client_sites, clients,
index_history, index_results, system_config
```

- [ ] **步骤 2：验证系统配置默认值**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring \
  -c "SELECT config_key, config_value FROM system_config ORDER BY config_key;"
```

预期输出 8 条配置记录。

- [ ] **步骤 3：插入测试客户数据**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring -c "
INSERT INTO clients (client_id, username, password_hash, company_name)
VALUES ('test_client_001', 'testuser', '\$2b\$12\$placeholder_hash_for_testing', '测试客户公司');

INSERT INTO client_sites (client_id, site_name, domain, site_type)
VALUES ('test_client_001', '测试官网', 'example.com', 'official');

INSERT INTO article_distributions (article_id, remote_url, status)
VALUES ('art_001', 'https://example.com/test-article-1', 'synced');
"
```

- [ ] **步骤 4：验证测试数据写入成功**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring \
  -c "SELECT * FROM clients; SELECT * FROM client_sites; SELECT * FROM article_distributions;"
```

**验收标准：**
- 7 张表全部存在
- 8 条默认配置正确
- 测试客户数据写入成功

---

### 任务 8：收录检测服务 API 测试

- [ ] **步骤 1：测试健康检查接口**

```bash
curl http://localhost:8090/health
```

预期输出：
```json
{"status": "healthy", "version": "1.0.0"}
```

- [ ] **步骤 2：测试收录检测接口（手动触发）**

```bash
curl -X POST http://localhost:8090/api/v1/index/check \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/test-article-1", "client_id": "test_client_001", "site_type": "official"}'
```

预期输出：
```json
{"code": 200, "msg": "检测任务已执行"}
```

- [ ] **步骤 3：验证收录结果写入数据库**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring \
  -c "SELECT url, baidu_status, toutiao_status, bing_status FROM index_results;"
```

预期输出：1 条记录，各搜索引擎状态为 `indexed` 或 `not_indexed`。

- [ ] **步骤 4：测试历史记录写入**

```bash
docker exec geo-postgres-local psql -U geo_user -d geo_monitoring \
  -c "SELECT url, check_date, total_indexed FROM index_history;"
```

预期输出：1 条历史记录，total_indexed 为 0-5 之间的数字。

- [ ] **步骤 5：测试系统配置接口**

```bash
# 读取配置
curl http://localhost:8090/api/v1/config

# 更新收录检测频率
curl -X PUT http://localhost:8090/api/v1/config \
  -H "Content-Type: application/json" \
  -d '{"index_scan_frequency": "2"}'
```

- [ ] **步骤 6：测试立即扫描接口**

```bash
curl -X POST http://localhost:8090/api/v1/scan/trigger/index
```

预期输出：
```json
{"code": 200, "msg": "扫描任务已触发"}
```

**验收标准：**
- 健康检查通过
- 收录检测功能正常，结果写入数据库
- 历史记录正确生成
- 配置读写正常
- 立即扫描触发成功

---

### 任务 9：Dashboard 前端功能测试

- [ ] **步骤 1：测试登录流程**

1. 浏览器访问 http://localhost:3000
2. 应自动跳转到 /login
3. 输入测试账号：testuser / 测试密码
4. 点击登录，应跳转到 Dashboard 主页

- [ ] **步骤 2：测试 Dashboard 数据展示**

1. 主页应显示 4 个统计卡片（总文章数、已收录数、收录率、AI 采信数）
2. 收录趋势图应正常渲染
3. 搜索引擎分布饼图应正常渲染

- [ ] **步骤 3：测试文章列表**

1. 导航到 /articles
2. 应显示测试文章列表
3. 各搜索引擎收录状态应正确显示

- [ ] **步骤 4：测试系统设置**

1. 导航到 /settings
2. 应显示扫描频率配置项
3. 修改频率后点击保存，应提示成功
4. 点击"立即收录扫描"按钮，应提示"扫描任务已触发"
5. 点击"立即 AI 采信扫描"按钮，应提示"扫描任务已触发"

- [ ] **步骤 5：测试文章详情弹窗**

1. 在文章列表中点击文章标题
2. 应弹出详情窗口
3. 应显示文章元信息、收录状态、原文快照
4. 点击"查看原文"应打开新窗口
5. 点击"关闭"应关闭弹窗

- [ ] **步骤 6：测试鉴权失效**

1. 清除 localStorage 中的 token
2. 刷新页面
3. 应自动跳转到 /login

**验收标准：**
- 登录流程正常
- Dashboard 数据展示正常
- 文章列表和详情弹窗正常
- 系统设置和立即扫描功能正常
- 鉴权机制生效

---

### 任务 10：单元测试与回归测试

- [ ] **步骤 1：运行后端单元测试**

```bash
docker exec geo-index-monitor-local pytest tests/ -v --tb=short
```

预期输出：所有测试 PASSED，无 FAILED。

- [ ] **步骤 2：测试爬虫并发控制**

```bash
docker exec geo-index-monitor-local pytest tests/test_spider.py -v
```

- [ ] **步骤 3：测试定时任务调度**

```bash
# 查看调度器状态
curl http://localhost:8090/api/v1/scheduler/status

# 预期输出调度任务列表
```

- [ ] **步骤 4：清理本地测试数据**

```bash
# 停止本地环境
docker compose -f docker-compose.local.yml down

# 清理数据卷（谨慎操作，会删除所有数据）
docker compose -f docker-compose.local.yml down -v
```

**验收标准：**
- 所有单元测试通过
- 爬虫并发控制生效
- 定时任务调度正常
- 本地测试环境可清理

---

### 任务 11：本地测试总结与上云前检查

- [ ] **步骤 1：填写本地测试检查清单**

```
本地测试检查清单：
[ ] PostgreSQL 容器运行正常
[ ] Redis 容器运行正常
[ ] 收录检测服务启动正常
[ ] Dashboard 启动正常
[ ] 数据库表结构完整（7 张表）
[ ] 系统配置默认值正确（8 条）
[ ] 健康检查接口通过
[ ] 收录检测功能正常（手动触发 + 结果入库）
[ ] 历史记录生成正常
[ ] 配置读写正常
[ ] 立即扫描功能正常
[ ] 登录流程正常
[ ] Dashboard 数据展示正常
[ ] 文章列表和详情弹窗正常
[ ] 系统设置和立即扫描正常
[ ] 鉴权机制生效
[ ] 单元测试全部通过
[ ] 定时任务调度正常
```

- [ ] **步骤 2：代码提交并打标签**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add -A
git commit -m "test: 完成本地集成测试，所有功能验证通过"
git tag v0.1.0-local-tested
```

- [ ] **步骤 3：确认所有验收标准通过后再进入云端部署**

**上云前置条件（全部必须为 ✅）：**
- [ ] 本地测试检查清单全部通过
- [ ] 无未解决的 bug
- [ ] 代码已提交并打标签
- [ ] `.env` 生产配置已准备（密码、密钥）
- [ ] 服务器可访问（SSH 登录正常）

**验收标准：**
- 本地测试检查清单 100% 通过
- 代码版本已固化（tag）
- 上云前置条件全部满足

---

## 阶段三：云端部署（第 8 天）

> **前置条件：阶段二本地测试全部通过。未通过本地测试禁止上云。**

### 任务 12：服务器环境初始化

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
sudo apt install -y curl git vim htop net-tools ufw fail2ban

# 配置防火墙
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# 配置系统参数
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
```

- [ ] **步骤 2：上传并执行初始化脚本**

```bash
chmod +x deploy/scripts/init-server.sh
scp deploy/scripts/init-server.sh ubuntu@124.220.33.188:/tmp/
ssh ubuntu@124.220.33.188 'bash /tmp/init-server.sh'
```

- [ ] **步骤 3：验证 Docker 环境**

```bash
ssh ubuntu@124.220.33.188
docker --version       # 预期：Docker version 29.6.1
docker compose version # 预期：Docker Compose version v5.3.1
```

- [ ] **步骤 4：创建项目目录**

```bash
ssh ubuntu@124.220.33.188
sudo mkdir -p /opt/geo-monitoring
sudo chown ubuntu:ubuntu /opt/geo-monitoring
```

**验收标准：**
- 系统更新完成
- 防火墙仅开放 22/80/443
- Docker 版本正确
- 项目目录创建完成

---

### 任务 13：上传代码与生产配置

- [ ] **步骤 1：上传项目文件到服务器**

```bash
rsync -avz --exclude='node_modules' --exclude='vendor' --exclude='.git' \
  --exclude='__pycache__' --exclude='*.pyc' \
  "/home/tishensnoopy/GEO FLOW+LUMORA CITE/" \
  ubuntu@124.220.33.188:/opt/geo-monitoring/
```

- [ ] **步骤 2：创建生产环境变量文件**

```bash
ssh ubuntu@124.220.33.188
cat > /opt/geo-monitoring/.env << 'EOF'
POSTGRES_PASSWORD=此处替换为强密码
REDIS_PASSWORD=此处替换为强密码
JWT_SECRET=此处替换为随机字符串
DEBUG=false
EOF

chmod 600 /opt/geo-monitoring/.env
```

- [ ] **步骤 3：创建生产 docker-compose 配置**

```yaml
# /opt/geo-monitoring/docker-compose.prod.yml
version: '3.8'

services:
  postgres:
    image: postgres:15-alpine
    container_name: geo-postgres
    restart: always
    env_file: .env
    environment:
      POSTGRES_DB: geo_monitoring
      POSTGRES_USER: geo_user
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./deploy/scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    ports:
      - "127.0.0.1:5432:5432"
    deploy:
      resources:
        limits: { memory: 1G, cpus: '0.5' }
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U geo_user -d geo_monitoring"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: geo-redis
    restart: always
    env_file: .env
    command: sh -c 'redis-server --requirepass "$$REDIS_PASSWORD"'
    volumes:
      - redis_data:/data
    ports:
      - "127.0.0.1:6379:6379"
    deploy:
      resources:
        limits: { memory: 512M, cpus: '0.25' }

  index-monitor:
    build: ./index-monitor
    container_name: geo-index-monitor
    restart: always
    env_file: .env
    environment:
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      DEBUG: "false"
    depends_on:
      postgres: { condition: service_healthy }
    ports:
      - "127.0.0.1:8090:8090"
    deploy:
      resources:
        limits: { memory: 512M, cpus: '0.5' }

  dashboard:
    build: ./dashboard
    container_name: geo-dashboard
    restart: always
    depends_on:
      - index-monitor
    ports:
      - "127.0.0.1:3000:80"
    deploy:
      resources:
        limits: { memory: 256M, cpus: '0.25' }

  nginx:
    image: nginx:alpine
    container_name: geo-nginx
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./deploy/nginx/conf.d:/etc/nginx/conf.d
    depends_on:
      - dashboard
      - index-monitor
    deploy:
      resources:
        limits: { memory: 256M, cpus: '0.25' }

volumes:
  postgres_data:
  redis_data:
```

**验收标准：**
- 项目文件上传完成
- `.env` 文件权限为 600
- 生产 docker-compose 配置创建完成

---

### 任务 14：启动生产服务与验证

- [ ] **步骤 1：构建并启动生产服务**

```bash
ssh ubuntu@124.220.33.188
cd /opt/geo-monitoring
docker compose -f docker-compose.prod.yml up -d --build

# 查看服务状态
docker compose -f docker-compose.prod.yml ps
```

预期输出：所有 5 个容器运行正常。

- [ ] **步骤 2：验证生产环境健康检查**

```bash
# 收录检测服务
curl http://124.220.33.188/api/v1/health

# Dashboard 页面
curl -I http://124.220.33.188/
```

- [ ] **步骤 3：验证数据库初始化**

```bash
docker exec geo-postgres psql -U geo_user -d geo_monitoring -c "\dt"
```

预期输出 7 张表。

- [ ] **步骤 4：浏览器访问验证**

1. 访问 http://124.220.33.188/ 应看到登录页
2. 创建生产客户账号
3. 登录后查看 Dashboard
4. 测试文章列表、设置页

- [ ] **步骤 5：配置数据库备份定时任务**

```bash
ssh ubuntu@124.220.33.188
crontab -e

# 添加以下内容：
# 每周日凌晨 4:00 数据库备份
0 4 * * 0 /opt/geo-monitoring/deploy/scripts/backup.sh
# 每日凌晨 5:00 清理 30 天前日志
0 5 * * * find /var/log -type f -mtime +30 -delete
```

- [ ] **步骤 6：最终验收与提交**

```bash
cd "/home/tishensnoopy/GEO FLOW+LUMORA CITE"
git add -A
git commit -m "deploy: 完成云端部署，生产环境上线"
git tag v1.0.0-prod
```

**验收标准：**
- 5 个生产容器全部运行
- 健康检查通过
- 数据库表结构完整
- 浏览器访问 Dashboard 正常
- 备份定时任务配置完成
- 生产版本打标签 v1.0.0-prod

---

## 部署检查清单汇总

### 本地测试阶段（阶段二）必须全部通过：
- [ ] 7 张数据库表创建完整
- [ ] 8 条系统配置默认值正确
- [ ] 健康检查接口通过
- [ ] 收录检测功能正常
- [ ] Dashboard 所有页面正常
- [ ] 立即扫描功能正常
- [ ] 鉴权机制生效
- [ ] 单元测试全部通过

### 云端部署阶段（阶段三）验收：
- [ ] 服务器环境初始化完成
- [ ] Docker 版本正确（29.6.1 + Compose v5.3.1）
- [ ] 防火墙仅开放 22/80/443
- [ ] 5 个生产容器运行正常
- [ ] 生产环境健康检查通过
- [ ] 浏览器访问 Dashboard 正常
- [ ] 数据库备份定时任务配置完成
- [ ] 生产版本标签 v1.0.0-prod 已打

---

**计划完成！**