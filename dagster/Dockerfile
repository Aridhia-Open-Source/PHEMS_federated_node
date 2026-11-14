FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git && \
    rm -rf /var/lib/apt/lists/*

# setup the dagster home directory
ENV DAGSTER_HOME=/opt/dagster/home
WORKDIR $DAGSTER_HOME

# Install locked third-party deps
# proxy_ca is an optional build secret (CUSTOM_CA_FILE): behind a TLS-inspecting proxy pip
# trusts it for this step only, nothing is kept in the image. See PROXY_CA_SETUP.md.
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca --mount=type=tmpfs,target=/ca \
    if [ -s /run/secrets/proxy_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /ca/bundle.crt \
        && export PIP_CERT=/ca/bundle.crt; \
    fi; \
    pip install --no-cache-dir -r requirements.txt

# Copy package source (uses .dockerignore to limit scope)
COPY . .

# Install package code in editable mode
RUN --mount=type=secret,id=proxy_ca --mount=type=tmpfs,target=/ca \
    if [ -s /run/secrets/proxy_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /ca/bundle.crt \
        && export PIP_CERT=/ca/bundle.crt; \
    fi; \
    pip install --no-cache-dir -e .

ENV PYTHONUNBUFFERED=1
EXPOSE 80
