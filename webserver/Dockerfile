FROM python:3.13.5-slim

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /app

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
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME"

COPY --chown=${USERNAME}:${USERNAME} . .

USER ${USER_UID}

EXPOSE 5000

ENTRYPOINT ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
