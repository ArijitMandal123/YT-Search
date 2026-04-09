FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default to 7860 for Hugging Face Spaces, Render will override this with its own PORT
ENV PORT=7860

# Increased timeout to 120s (was default 30s) to handle slow proxy responses.
# 2 workers for better concurrency on free tier.
# --preload speeds up worker startup by loading the app before forking.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 2 --preload --log-file - --log-level info
