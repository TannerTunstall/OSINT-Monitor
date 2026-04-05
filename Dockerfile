FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    yt-dlp curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

RUN mkdir -p data logs session && \
    chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8550/api/health || exit 1

CMD ["python", "-m", "src.main"]
