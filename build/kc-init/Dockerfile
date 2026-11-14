FROM python:3.13.5-slim

ARG APP_USER=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /scripts

# Copy requirements first for better caching
COPY requirements.txt .

# proxy_ca is an optional build secret (CUSTOM_CA_FILE): behind a TLS-inspecting proxy pip
# trusts it for this step only, nothing is kept in the image. See PROXY_CA_SETUP.md.
RUN --mount=type=secret,id=proxy_ca --mount=type=tmpfs,target=/ca \
    if [ -s /run/secrets/proxy_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /ca/bundle.crt \
        && export PIP_CERT=/ca/bundle.crt; \
    fi; \
    pip install --no-cache-dir -r requirements.txt

# Create non-root user
RUN groupadd -g "$USER_GID" "$APP_USER" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$APP_USER"

# Copy application code with correct ownership
COPY --chown=${USER_UID}:${USER_GID} *.py .
COPY --chown=${USER_UID}:${USER_GID} migrations/ ./migrations/

USER ${USER_UID}

ENTRYPOINT ["/bin/sh", "-c", "python3 -u /scripts/setup_realm.py && tail -f /dev/null"]