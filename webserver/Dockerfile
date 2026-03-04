FROM python:3.13.5-slim

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /webserver

# Install system dependencies
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -g "$USER_GID" "$USERNAME" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$USERNAME"

# Copy application code with correct ownership
COPY --chown=${USER_UID}:${USER_GID} . .

USER ${USER_UID}

EXPOSE 5000

ENTRYPOINT ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
