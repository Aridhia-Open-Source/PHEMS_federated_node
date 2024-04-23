FROM python:3.12

# hadolint ignore=SC1070
ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

COPY app /app
COPY migrations /migrations
COPY alembic.ini /

WORKDIR /app

# hadolint detects pipenv as another invocation of pip
# hadolint ignore=DL3013,DL3008
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install --no-install-recommends -y \
        libpq-dev \
        python3-dev \
        gcc \
    && pip install --no-cache-dir --upgrade pip \
    && PATH=$(which pg_config):$PATH \
    && python3 -m pip install --no-cache-dir pipenv \
    && pipenv lock \
    && pipenv install --system --deploy --categories packages \
    && pip uninstall -y pipenv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" "$USERNAME" \
    && chown -R "$USERNAME":"$USERNAME" /app

USER ${USER_UID}
EXPOSE 5000
WORKDIR /
ENTRYPOINT [ "waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "app:create_app"]
