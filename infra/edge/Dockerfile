FROM nginx:1.30.6-alpine
# Alpine security fixes land between base image releases; CI's Trivy gate
# fails on fixable HIGH and CRITICAL findings.
RUN apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
ARG COMMIT=unknown
ENV COMMIT=$COMMIT
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
