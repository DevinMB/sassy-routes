# Built from the repo root (it needs scoring.yaml): docker build -f backend/Dockerfile .
FROM python:3.12.14-slim-trixie AS base
# Debian security fixes land between base image releases; CI's Trivy gate
# fails on fixable HIGH and CRITICAL findings.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# The test suite runs as part of the build: the image below exists only if it
# passed. Dev dependencies stay in this stage.
FROM base AS test
COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY scoring.yaml /scoring.yaml
COPY backend/app ./app
COPY backend/tests ./tests
RUN python -m pytest -q -p no:cacheprovider tests && touch /tmp/tests-passed

FROM base
COPY --from=test /tmp/tests-passed /tmp/tests-passed
# pip leaves: it vendors its own certifi, msgpack and urllib3 (Trivy flags them)
# and nothing installs at runtime.
RUN pip check \
 && pip uninstall -y pip setuptools wheel \
 && rm -rf /root/.cache /usr/local/lib/python3*/ensurepip
COPY backend/app ./app
# Default scoring weights; the live stack may mount its own over this path.
COPY scoring.yaml /srv/scoring.yaml
RUN useradd --create-home apex
USER apex
ARG COMMIT=unknown
ENV COMMIT=$COMMIT PYTHONUNBUFFERED=1
EXPOSE 8000
# /api/health answers 200 whenever the process serves; GraphHopper's state is reported, not required.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
