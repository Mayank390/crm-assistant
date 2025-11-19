FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        libgomp1 \
        libstdc++6 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
COPY embedding_service/requirements.txt /tmp/embedding-requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/embedding-requirements.txt \
    && rm -rf /root/.cache

COPY embedding_service /app

RUN mkdir -p /app/.cache/huggingface

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
