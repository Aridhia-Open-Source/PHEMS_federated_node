FROM alpine/k8s:1.33.2

ARG APP_USER=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# Install system dependencies. With a proxy CA given (see the pip step) apk uses http
# repositories, which is safe because apk checks package signatures itself.
RUN --mount=type=secret,id=proxy_ca \
    if [ -s /run/secrets/proxy_ca ]; then sed -i 's|^https://|http://|' /etc/apk/repositories; fi; \
    apk add --no-cache \
    'postgresql16-client=~16'

# Copy requirements first for better caching
COPY requirements.txt /tmp/requirements.txt

# proxy_ca is an optional build secret (CUSTOM_CA_FILE): behind a TLS-inspecting proxy pip
# trusts it for this step only, nothing is kept in the image. See PROXY_CA_SETUP.md.
RUN --mount=type=secret,id=proxy_ca --mount=type=tmpfs,target=/ca \
    if [ -s /run/secrets/proxy_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /ca/bundle.crt \
        && export PIP_CERT=/ca/bundle.crt; \
    fi; \
    python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# Create non-root user
RUN addgroup -S "${APP_USER}" --gid "${USER_GID}" \
    && adduser -S "${APP_USER}" -G "${APP_USER}" -u "${USER_UID}"

# Install scripts to PATH
COPY --chown=${USER_UID}:${USER_GID} scripts/ /usr/bin/

RUN for f in /usr/bin/*.sh /usr/bin/*.py; do \
        mv "$f" "/usr/bin/$(basename "${f%.*}")"; \
    done

ENV PATH=/venv/bin:$PATH

USER ${USER_UID}