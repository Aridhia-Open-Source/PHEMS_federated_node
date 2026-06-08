FROM python:3.13.5-slim

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /scripts

# Copy requirements first for better caching
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -g "$USER_GID" "$USERNAME" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$USERNAME"

# Copy application code with correct ownership
COPY --chown=${USER_UID}:${USER_GID} *.py .

USER ${USER_UID}

ENTRYPOINT ["/bin/sh", "-c", "python3 /scripts/setup_realm.py && tail -f /dev/null"]