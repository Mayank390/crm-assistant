FROM python:3.11-slim

ENV HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONUNBUFFERED=1

# OS dependencies required by torch / transformers
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libstdc++6 ca-certificates curl netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./requirements.txt
COPY data-sync/consumer/requirements.txt ./consumer-requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 --retries=5 -r requirements.txt && \
    pip install --no-cache-dir --default-timeout=300 --retries=5 -r consumer-requirements.txt

# Copy application code and shared qdrant modules
COPY data-sync/qdrant ./qdrant
COPY embedding ./embedding
COPY splade ./splade
COPY data-sync/consumer/app ./app
COPY data-sync/backfill_mongodb.py ./backfill_mongodb.py
COPY data-sync/consumer/wait-for-qdrant.sh /usr/local/bin/wait-for-qdrant.sh

RUN chmod +x /usr/local/bin/wait-for-qdrant.sh

ENV PYTHONPATH="/app:${PYTHONPATH}"

ENTRYPOINT ["/usr/local/bin/wait-for-qdrant.sh"]
CMD ["python", "-m", "app.main"]
