FROM python:3.11-slim

# Install ffmpeg for yt-dlp media manipulation if needed
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to 7860 for Hugging Face Spaces, Render will override this with its own PORT
ENV PORT=7860

CMD gunicorn app:app --bind 0.0.0.0:$PORT --log-file -
