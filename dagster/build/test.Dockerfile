FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

# Install locked third-party deps first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Package plus the dev extras (pytest, pylint)
RUN pip install --no-cache-dir -e ".[dev]"

ENV PYTHONUNBUFFERED=1
