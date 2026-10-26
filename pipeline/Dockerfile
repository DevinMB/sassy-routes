FROM python:3.12.14-slim-trixie AS base
# pyosmium links against system libexpat; Debian security fixes applied too.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends libexpat1 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Tests run during the build; the image below exists only if they passed.
FROM base AS test
RUN pip install --no-cache-dir pytest==9.1.1
COPY scorer ./scorer
COPY tests ./tests
RUN python -m pytest -q -p no:cacheprovider tests && touch /tmp/tests-passed

FROM base
COPY --from=test /tmp/tests-passed /tmp/tests-passed
RUN pip check \
 && pip uninstall -y pip setuptools wheel \
 && rm -rf /root/.cache /usr/local/lib/python3*/ensurepip
COPY scorer ./scorer
RUN useradd --create-home apex
USER apex
ARG COMMIT=unknown
ENV COMMIT=$COMMIT
# A batch job, run on demand (make pipeline): no HEALTHCHECK.
CMD ["python", "-m", "scorer"]
