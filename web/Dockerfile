# Build context: repository root (like the api image), so the shared /api proxy fragment
# deploy/nginx/api-proxy.conf is used as is. Works with the classic builder and BuildKit:
#   docker build -f web/Dockerfile -t alfa-credit/web:local .
ARG NODE_IMAGE=node:22.23.3-alpine
ARG NGINX_IMAGE=nginx:1.30.6-alpine

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV CI=true
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/tsconfig.json web/vite.config.ts web/index.html ./
COPY web/public ./public
COPY web/src ./src
RUN npm run typecheck && npm run build

FROM ${NGINX_IMAGE} AS runtime
RUN rm -f /etc/nginx/conf.d/default.conf && mkdir -p /etc/nginx/snippets
COPY web/nginx/nginx.conf /etc/nginx/nginx.conf
COPY web/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY web/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY deploy/nginx/api-proxy.conf /etc/nginx/snippets/api-proxy.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
