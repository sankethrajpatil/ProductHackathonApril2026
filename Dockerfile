# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.12-slim

# Non-root user for security
RUN groupadd -r splitbot && useradd -r -g splitbot splitbot

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/
COPY webapp/ ./webapp/

# Drop to non-root
USER splitbot

# Health check against the aiohttp server
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

CMD ["python", "-m", "app.main"]
