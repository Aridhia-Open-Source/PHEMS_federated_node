FROM python:3.13.5-slim

ARG USERNAME=gitea-mirror
ARG USER_UID=1001
ARG USER_GID=1001

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
        curl \
        jq \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt .

RUN pip install --no-cache-dir -r requirements-dev.txt

RUN groupadd -g "$USER_GID" "$USERNAME" && \
    useradd --uid "$USER_UID" --gid "$USER_GID" --create-home "$USERNAME"

COPY --chown=${USER_UID}:${USER_GID} . .

RUN mkdir -p /app/artifacts && chown -R ${USER_UID}:${USER_GID} /app

USER ${USER_UID}

EXPOSE 5000

ENTRYPOINT ["pytest"]
