FROM python:3.11-slim

WORKDIR /app

# Install Deno JS runtime (required by yt-dlp for YouTube PO token generation)
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip && \
    curl -fsSL https://deno.land/install.sh | sh && \
    ln -s /root/.deno/bin/deno /usr/local/bin/deno && \
    apt-get purge -y curl unzip && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install ffmpeg (required by yt-dlp for merging adaptive streams)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to 7860 for Hugging Face Spaces, Render will override this with its own PORT
ENV PORT=7860

# Increased timeout to 120s (was default 30s) to handle slow proxy responses.
# 2 workers for better concurrency on free tier.
# --preload speeds up worker startup by loading the app before forking.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2 --preload --log-file - --log-level info
