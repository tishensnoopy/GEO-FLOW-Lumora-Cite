# GEO内容分发\+收录AI监测系统 分步落地部署清单（可直接执行）

**适配环境**：2核4G / 40G磁盘 / 单机云服务器 / 自有域名

**最终架构**：Nginx \+ 公司官网（静态）\+ GEOFlow（生产中台）\+ 自研监测服务 \+ 客户鉴权报表

**核心原则**：先稳基础、再通业务、最后做客户交付；全程错峰限流、内网隔离、数据防泄露

## 第一阶段：服务器基础环境初始化（前置必做，P0）

**目标**：统一运行环境、规避资源爆满、权限、网络基础问题

- **1\. 系统更新与基础依赖安装（一键命令）**`apt update && apt upgrade -y
``apt install -y docker.io docker-compose git python3 python3-pip nginx cron`

- **2\. 配置服务器资源防护（适配2核4G低配）OOM内存防护配置**（防止核心服务被杀死）
`echo "vm.overcommit_memory=1" >> /etc/sysctl.conf
``sysctl -p`

- **日志自动轮转配置（解决40G磁盘瓶颈）**新建全局日志切割配置 `/etc/logrotate.d/global-log/var/log/*.log /root/*.log /var/lib/docker/containers/*/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    maxsize 100M
``}`

- **进程/文件数限制优化**修改 `/etc/security/limits.conf` 末尾添加：`* soft nofile 65535
* hard nofile 65535
* soft nproc 16384
``* hard nproc 16384`

- **3\. 安全组/防火墙放行（仅保留必要端口）**`ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
``ufw enable`

- **4\. 域名与SSL基础配置前置**提前解析：主域名=官网，子域名=admin\.xxx\.com（GEOFlow）、data\.xxx\.com（客户报表）SSL推荐使用acme\.sh一键免费证书，提前部署全站HTTPS

- **5\. Nginx基础全局配置**内网服务拦截：监测服务仅容器互通，禁止公网访问

- 通用限流、超时、SSL强制跳转配置，统一写入nginx\.conf

```Plain Text
# /etc/nginx/nginx.conf 核心优化片段
worker_processes 2; # 适配2核CPU
worker_connections 1024;
keepalive_timeout 60;
client_max_body_size 10M;
limit_req_zone $binary_remote_addr zone=geo_limit:10m rate=10r/s;

```

- **6\. 统一PostgreSQL数据库部署（单库共用）**Docker快速部署命令（适配低配，资源限制）`docker run -d \
--name geo-postgres \
--restart always \
--memory 1G \
--cpus 0.5 \
-v /data/postgres:/var/lib/postgresql/data \
-e POSTGRES_USER=geouser \
-e POSTGRES_PASSWORD=Geo@2026 \
-e POSTGRES_DB=geodb \
-p 5432:5432 \
postgres:15-alpine
`

## 第二阶段：核心服务部署顺序（严格按此顺序，防冲突）

**部署优先级逻辑**：静态服务优先 \> 核心业务中台 \> 内网监测服务 \> 交付层报表

### 步骤1：部署公司官网（纯静态，最低资源占用）

- 部署纯静态官网，资源极致轻量化，无动态程序、无定时任务站点根目录：`/var/www/official`，直接放入静态html/css/js

- Nginx官网站点配置 `/etc/nginx/sites-available/official.confserver {
    listen 80;
    server_name 你的主域名.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name 你的主域名.com;

    ssl_certificate 证书路径;
    ssl_certificate_key 证书路径;

    root /var/www/official;
    index index.html;

    # 静态资源缓存
    location ~* \.(jpg|png|css|js|ico)$ {
        expires 30d;
    }
}`启用站点命令：`ln -s /etc/nginx/sites-available/official.conf /etc/nginx/sites-enabled/
``nginx -t && systemctl restart nginx`

### 步骤2：部署 GEOFlow（业务生产中枢）

- **GEOFlow 部署完整流程**`# 拉取源码
git clone https://github.com/yaojingang/GEOFlow.git /opt/geoflow
cd /opt/geoflow

# 新建.env配置文件（适配低配+统一数据库）
cat > .env << EOF
DB_HOST=geo-postgres
DB_PORT=5432
DB_USER=geouser
DB_PASS=Geo@2026
DB_NAME=geodb
MAX_AI_TASK=2 # 核心限流：2核4G最大并发2个生成任务
API_PREFIX=/api
EOF

# 启动docker-compose
``docker-compose up -d`

- 后台初始化：填入大模型API密钥、搭建关键词库、SEO提示词模板

- 强制限流生效：固定 **MAX\_AI\_TASK=2**，杜绝内存溢出OOM

- 预设客户推送模板：适配WordPress REST API、通用POST推送接口

- 基础链路测试：手动生成文章，调用推送接口，校验返回完整文章URL

**本阶段关键改造（闭环必备）GEOFlow Webhook配置模板**

新增推送成功回调接口，文章发布成功后自动POST数据到自研监测服务内网地址，请求体JSON格式：

```Plain Text
{
  "client_id": "客户唯一ID",
  "domain": "客户域名",
  "article_url": "客户站点落地URL",
  "article_title": "文章标题",
  "push_time": "2026-XX-XX XX:XX:XX"
}
```

内网回调地址固定：`http://monitor-service:8090/webhook/geo-push`（仅容器内网可访问）

### 步骤3：部署自研监测服务（内网封闭，不公网暴露）

- **自研监测服务部署规范（纯内网、无公网端口）**服务端口：8090（仅容器内网监听），不映射宿主机端口

- **监测规则配置模板（低配专属）**支持引擎：百度、头条、搜狗、360、必应收录检测

- 爬虫核心参数（防封禁\+低配适配）
`# 爬虫全局配置
SPIDER_CONCURRENT=3      # 最大并发3
SPIDER_INTERVAL=2-5      # 随机间隔2-5秒
USER_AGENT_ROTATE=true   # UA轮换
RETRY_TIMES=2            # 失败重试2次
`

- 定时任务Cron配置（错峰避坑）
`# 白天 9:00-22:00 每6小时增量检测新文章
0 0,6,12,18 * * *
# 凌晨 2:00 全量批量巡检（低资源冲突）
0 2 * * *
`

- **AI抽样检测定时配置**`# 每周一、周四凌晨3点抽样检测AI采信效果
0 3 * * 1,4
# 单次检测最大文章数：20篇（严控Token成本）
`

- 数据自动入库，关联客户ID、多引擎收录状态、AI参考结果，建立数据索引优化查询速度

### 步骤4：部署客户交付层（鉴权\+报表分享）

- 独立轻量化报表站点，部署在子域名`data.xxx.com`，无后台冗余功能

- **核心功能配置与代码模板**客户管理：绑定域名、客户唯一ID、权限状态

- Token鉴权规则
`# 分享链接规则
TOKEN_EXPIRE_DAY=30  # 链接默认30天过期
TOKEN_RANDOM_LEN=16  # 16位随机密钥
# 访问规则：无Token禁止访问、过期Token自动失效、仅查看自身数据
`

- 数据租户隔离：SQL查询强制携带 `client_id`过滤，杜绝跨客户数据泄露

- 报表展示字段固定：发文总数、各搜索引擎收录数、收录趋势图、单篇文章状态、AI抽样参考结果、检测时间

## 第三阶段：系统打通与全链路测试（验证业务闭环）

**目标**：跑通完整业务流程，排查推送、监测、数据同步、权限漏洞

- 1\. 手动触发GEOFlow文章生成 \& 客户站点推送

- 2\. 验证Webhook自动同步URL至监测服务

- 3\. 等待一轮巡检，验证搜索引擎收录数据正常入库

- 4\. 验证AI抽样检测数据正常生成并标注「参考数据」

- 5\. 后台生成客户分享链接，测试访问鉴权、数据隔离有效性

- 6\. 压力测试：开启定时任务，观察CPU/内存是否触发OOM、服务卡顿

- 7\. 异常测试：模拟客户站点接口失效，验证推送失败重试、日志记录正常

## 第四阶段：上线前安全与稳定性固化（商用必备）

- **密钥加密存储**：所有API密钥、客户CMS凭证存入环境变量/加密配置，删除所有明文配置文件

- **服务安全关闭**：关闭所有服务debug模式、内网监测服务禁止任何公网路由穿透

- **任务时刻表固化**：写入定时任务文档，禁止人工随意新增高并发任务

- **基础告警配置**：磁盘使用率＞85%、服务宕机触发日志告警

- **客户话术固化**：前台报表固定标注「AI检测结果为周期性抽样参考，仅作效果辅助评估」

- **备份\&清理定时任务（一键写入）**`# 每周日凌晨4点数据库备份
0 4 * * 0 /root/backup_db.sh
# 每日凌晨5点清理30天前过期日志
0 5 * * * find /var/log -type f -mtime +30 -delete
`

## 第五阶段：可选内测（短期 lumora\-cite 对比验证）

仅内部测试、不对外商用：

- 内网独立部署lumora\-cite，不占用公网端口、不接入生产业务

- 小批量测试50篇以内文章，对比自研服务AI检测准确率、收录数据一致性

- 记录资源占用数据，作为技术储备，不用于客户正式报表输出

## 第六阶段：正式商用上线标准

满足以下全部条件即可对外接客户：

- 全链路自动化跑通：生成→推送→监测→报表展示

- 无服务卡顿、OOM、数据丢失问题

- 客户数据隔离、Token鉴权、链接时效功能正常

- 异常推送可重试、日志可追溯

- 磁盘、内存资源稳定无溢出

## 常驻运维规范（适配低配服务器）

- 严格执行：凌晨2点全量巡检、日间仅增量检测新文章，规避CPU/内存高峰拥堵

- 每周手动清理无效监测数据、过期日志，释放磁盘空间

- 每月1号自动全量数据库备份，留存历史客户数据

- 永久禁止：同时运行3个及以上高耗资源任务，不新增无关服务

> （注：部分内容可能由 AI 生成）
