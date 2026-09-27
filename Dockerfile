# Production image for the API (used by Render, or any Docker host)
FROM python:3.13-slim

# Print logs straight away and don't write .pyc files
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install packages first, so Docker can reuse this layer when only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Don't run as root
RUN useradd --create-home appuser
USER appuser

# Render tells the app which port to use in $PORT; 8000 is the default elsewhere
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
