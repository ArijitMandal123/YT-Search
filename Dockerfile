FROM python:3.11-slim

WORKDIR /app

# Install basic system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=7860

# Metadata search is lightweight, 2 workers is fine for higher concurrency on free tier
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2 --preload --log-file - --log-level info
