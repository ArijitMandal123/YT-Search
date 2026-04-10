FROM python:3.11-slim

WORKDIR /app

# Install system dependencies: curl for Deno, ffmpeg for stream merging
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Deno JS runtime (used by yt-dlp for YouTube PO token generation)
RUN curl -fsSL https://deno.land/install.sh | sh && \
    ln -s /root/.deno/bin/deno /usr/local/bin/deno

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Always upgrade yt-dlp to latest at build time to get newest YouTube bypass patches
RUN pip install --no-cache-dir --upgrade yt-dlp

COPY . .

ENV PORT=7860

# single worker is safer on free 512MB RAM, timeout 120s for slow proxies
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1 --preload --log-file - --log-level info
