FROM python:3.13.5-slim

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
        curl \
        jq \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

# Create non-root user
RUN groupadd -g "$USER_GID" "$USERNAME" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$USERNAME"

# Copy application code with correct ownership
COPY --chown=${USER_UID}:${USER_GID} . .

# WORKDIR is root-owned; grant the non-root user write access so coverage can
# create its temp db files in /app and write artifacts/coverage.xml
RUN mkdir -p /app/artifacts && chown -R ${USER_UID}:${USER_GID} /app

USER ${USER_UID}

EXPOSE 5000

ENTRYPOINT ["./test-entrypoint.sh"]