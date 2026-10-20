# Use Python 3.14 slim image
FROM python:3.14-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        git \
        curl \
        redis-tools \
        tesseract-ocr \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

# Copy pyproject.toml, uv.lock, and README.md
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy project
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# Default command - use PORT environment variable
CMD ["sh", "-c", "exec /app/.venv/bin/gunicorn --bind 0.0.0.0:${PORT:-8000} credit_mate_ai.wsgi:application"]
