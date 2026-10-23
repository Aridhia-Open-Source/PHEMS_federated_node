FROM python:3.13.5-slim

ARG APP_USER=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /webserver

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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

RUN groupadd -g "$USER_GID" "$APP_USER" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$APP_USER"

COPY --chown=${APP_USER}:${APP_USER} . .

USER ${USER_UID}

EXPOSE 5000

ENTRYPOINT ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
