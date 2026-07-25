# index-monitor/Dockerfile（生产版，国内镜像源适配）
FROM python:3.11-slim

WORKDIR /app

# 国内镜像源适配（与 Dockerfile.local 一致，解决 deb.debian.org/pypi.org 超时）
# fonts-noto-cjk：PDF 导出中文渲染必需
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y gcc libpq-dev fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

# Playwright Chromium + 系统依赖（M3 PDF 导出需要）
# 注意：playwright install-deps 在 Debian Trixie 上包名解析不稳，改用显式包列表
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxcb1 libxkbcommon0 libatspi2.0-0 libx11-6 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
        libasound2t64 \
    && playwright install chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
