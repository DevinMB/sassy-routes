FROM python:3.12-slim

# pyosmium links against system libexpat
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scorer ./scorer

RUN useradd --create-home apex
USER apex

CMD ["python", "-m", "scorer"]
