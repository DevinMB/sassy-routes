FROM node:26.11.1-alpine AS build
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

# nginx stable serves the static build (Caddy 2.11.x still ships a Go runtime
# with fixable HIGH CVEs, 2026-10-26).
FROM nginx:1.30.6-alpine
# Alpine security fixes land between base image releases; CI's Trivy gate
# fails on fixable HIGH and CRITICAL findings.
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
ARG COMMIT=unknown
ENV COMMIT=$COMMIT
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
