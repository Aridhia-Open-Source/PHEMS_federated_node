FROM python:3.12

COPY ./ /app

WORKDIR /app/app
ENV PYTHONDONTWRITEBYTECODE=1

# hadolint detects pipenv as another invocation of pip
# hadolint ignore=DL3013
RUN apt-get update \
    && apt-get install -y libpq-dev python3-dev gcc \
    && pip install --upgrade pip \
    && PATH=$(which pg_config):$PATH \
    && python3 -m pip install --no-cache-dir pipenv \
    && pipenv lock \
    && pipenv install --system --deploy --categories "packages dev-packages" \
    && pip uninstall -y pipenv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

EXPOSE 5000
COPY --chmod=777 test-entrypoint.sh /app/
COPY setup.cfg /app/setup.cfg
ENTRYPOINT [ "./test-entrypoint.sh" ]
