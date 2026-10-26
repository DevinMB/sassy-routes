FROM node:22.23.3-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tsconfig.json vite.config.ts index.html ./
COPY src ./src
# The unit tests gate the build.
RUN npx vitest run
# '/' for production, '/beta/' for the staging build (see docker-compose.yml)
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE
RUN npm run build

# 2.11.7 is built with Go 1.26.9, fixing four HIGH stdlib/x/net CVEs in 2.11.6;
# taken before the usual two-week wait.
FROM caddy:2.11.7-alpine
# Alpine security fixes land between base image releases; CI's Trivy gate
# fails on fixable HIGH and CRITICAL findings.
RUN apk upgrade --no-cache
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
ARG COMMIT=unknown
ENV COMMIT=$COMMIT
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
