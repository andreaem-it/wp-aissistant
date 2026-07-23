FROM python:3.11-slim

# tesseract is required for OCR on uploaded images (pytesseract in app/rag.py)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Apply migrations, then serve. DATABASE_URL / LLM_* come from the environment.
# --proxy-headers makes uvicorn honour X-Forwarded-For/Proto when behind a reverse proxy, so
# request.client.host is the real client IP (needed for per-IP rate limiting). Restrict which
# upstreams are trusted with the FORWARDED_ALLOW_IPS env var when deploying behind a proxy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
