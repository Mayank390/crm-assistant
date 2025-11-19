FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        libgomp1 \
        libstdc++6 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
COPY splade_service/requirements.txt /tmp/splade-requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r /tmp/requirements.txt \
    && pip install -r /tmp/splade-requirements.txt \
    && rm -rf /root/.cache

COPY splade_service /app

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
