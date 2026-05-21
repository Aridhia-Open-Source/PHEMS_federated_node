FROM alpine/k8s:1.33.2

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

# Install system dependencies
RUN apk add --no-cache \
    'postgresql16-client=~16'

# Copy requirements first for better caching
COPY requirements.txt /tmp/requirements.txt

RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# Create non-root user
RUN addgroup -S "${USERNAME}" --gid "${USER_GID}" \
    && adduser -S "${USERNAME}" -G "${USERNAME}" -u "${USER_UID}"

# Install scripts to PATH
COPY --chown=${USER_UID}:${USER_GID} scripts/ /usr/bin/

RUN for f in /usr/bin/*.sh /usr/bin/*.py; do \
        mv "$f" "/usr/bin/$(basename "${f%.*}")"; \
    done

ENV PATH=/venv/bin:$PATH

USER ${USER_UID}