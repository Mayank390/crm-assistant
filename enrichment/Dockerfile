FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl wget gnupg libnss3 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo-gobject2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip install playwright && playwright install --with-deps chromium

RUN pip install "crawl4ai[all]" fastapi uvicorn pydantic groq --no-cache-dir

COPY server.py /app/server.py
RUN chmod +x /app/server.py

EXPOSE 11235

HEALTHCHECK --interval=30s --timeout=10s CMD curl -f http://localhost:11235/health || exit 1

CMD ["python", "/app/server.py"]
