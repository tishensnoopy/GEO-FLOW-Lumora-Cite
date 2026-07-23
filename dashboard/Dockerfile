# dashboard/Dockerfile（生产版，多阶段构建）
# 阶段1: Node 构建
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# 阶段2: nginx 部署静态资源
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# SPA 路由 fallback（Vue Router history 模式）
RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
